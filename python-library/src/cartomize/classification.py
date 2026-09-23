"""Supervised land-cover mapping and spectral clustering on bounded raster blocks.

Training/validation groups are split before pixel sampling. Models are stored
as numeric NPZ arrays with allow_pickle=False, never executable pickle files.
"""
from dataclasses import dataclass
from pathlib import Path
import json
import math
import numpy as np
import rasterio
from rasterio.features import geometry_mask,geometry_window
from rasterio.errors import WindowError
from rasterio.windows import Window
from matplotlib import colormaps
from matplotlib.colors import to_hex
from ._validation import frame,output_path
from .imagery import _check_cancel
from .nodata import _windows
from .raster import _writer
from .storage import new_directory,save_json,read_json


def _spectral(src,bands,window):
    data=np.ma.masked_invalid(src.read(bands,window=window,masked=True).astype('float64'))
    for i,b in enumerate(bands):data[i]=data[i]*src.scales[b-1]+src.offsets[b-1]
    valid=~np.ma.getmaskarray(data).any(axis=0)&np.isfinite(data.data).all(axis=0)
    return data.data,valid


def _bands(src,bands):
    if src.crs is None:raise ValueError('Le raster doit avoir un système de coordonnées.')
    if src.tags().get('CARTOMIZE_PRODUCT')=='display_rgba':raise ValueError('La classification nécessite le raster scientifique, avant étirement RVB.')
    result=list(bands or src.indexes)
    if not result or len(set(result))!=len(result) or any(not isinstance(b,int) or b not in src.indexes for b in result):
        raise ValueError('Sélectionner des bandes distinctes présentes dans le raster.')
    return result


def _class_table(data,column,label_column=None):
    if column not in data or data[column].isna().any():raise ValueError('Chaque échantillon doit avoir une classe renseignée.')
    raw=list(dict.fromkeys(data[column].tolist()))
    numeric=all(isinstance(x,(int,float,np.integer,np.floating)) and np.isfinite(x) and float(x)==int(x) and 0<=x<2**24 for x in raw)
    mapping={str(x):int(x) if numeric else i+1 for i,x in enumerate(sorted(raw,key=str))}
    if len(mapping)<2:raise ValueError('Fournir au moins deux classes distinctes.')
    palette=colormaps['tab20'].resampled(len(mapping));classes={}
    for i,(label,code) in enumerate(mapping.items()):
        subset=data[data[column].astype(str)==label]
        names=subset[label_column].dropna().astype(str).unique() if label_column and label_column in data else []
        if len(names)>1:raise ValueError(f'Plusieurs libellés pour la classe {label}.')
        classes[code]=[names[0] if len(names) else label,to_hex(palette(i))]
    return mapping,classes


def _sample_features(src,features,column,mapping,bands,limit,seed,cancel,excluded=None):
    """Stratified priority sampling in a single raster pass; bounded memory.

    Spatial indexes restrict each block to relevant reference features. Pixel
    conflicts and validation overlap are checked before sampling, including
    pixels which will not be retained in the reservoir.
    """
    from shapely.geometry import box
    from rasterio.windows import bounds as window_bounds
    rng=np.random.default_rng(seed);features=features.to_crs(src.crs)
    if features.geometry.isna().any() or features.geometry.is_empty.any() or not features.geometry.is_valid.all():raise ValueError('Géométries des échantillons absentes ou invalides.')
    if not features.geom_type.isin(['Point','MultiPoint','Polygon','MultiPolygon']).all():raise ValueError('Utiliser des points ou des polygones comme échantillons.')
    if column not in features or not set(features[column].astype(str))<=set(mapping):raise ValueError('Classes de référence inconnues ou absentes.')
    codes=features[column].astype(str).map(mapping).to_numpy();index=features.sindex
    if excluded is not None:excluded=excluded.to_crs(src.crs);excluded_index=excluded.sindex
    groups={code:(np.empty((0,len(bands))),np.empty(0),np.empty(0,dtype='int64')) for code in mapping.values()};cap=max(2,limit//len(groups))
    try:bounds=geometry_window(src,features.geometry,pad_x=.5,pad_y=.5)
    except WindowError:raise ValueError('Les échantillons ne recouvrent pas le raster.') from None
    for y in range(int(bounds.row_off),int(bounds.row_off+bounds.height),256):
        for x in range(int(bounds.col_off),int(bounds.col_off+bounds.width),256):
            _check_cancel(cancel)
            win=Window(x,y,min(256,int(bounds.col_off+bounds.width)-x),min(256,int(bounds.row_off+bounds.height)-y))
            hits=index.query(box(*window_bounds(win,src.transform)),predicate='intersects')
            if not len(hits):continue
            values,valid=_spectral(src,bands,win);assigned=np.full(valid.shape,-1,dtype='int64');transform=src.window_transform(win)
            for code in np.unique(codes[hits]):
                geometries=features.geometry.iloc[hits[codes[hits]==code]]
                inside=geometry_mask(geometries,valid.shape,transform,invert=True)&valid
                if ((assigned>=0)&inside).any():raise ValueError('Des échantillons de classes différentes couvrent le même pixel.')
                assigned[inside]=code
            if excluded is not None:
                other=excluded_index.query(box(*window_bounds(win,src.transform)),predicate='intersects')
                if len(other) and ((assigned>=0)&geometry_mask(excluded.geometry.iloc[other],valid.shape,transform,invert=True)).any():raise ValueError('Apprentissage et validation partagent des pixels ; utiliser des échantillons spatialement distincts.')
            for code in groups:
                rows,cols=np.where(assigned==code)
                if not len(rows):continue
                pixels=(rows+y)*src.width+cols+x;sample=values[:,rows,cols].T;priorities=rng.random(len(sample))
                old,old_priorities,old_ids=groups[code]
                sample=np.concatenate([old,sample]);priorities=np.concatenate([old_priorities,priorities]);ids=np.concatenate([old_ids,pixels])
                take=np.argpartition(priorities,min(cap,len(sample))-1)[:cap];groups[code]=(sample[take],priorities[take],ids[take])
    xs=[];ys=[];ids=[]
    for code,(values,_,pixel_ids) in groups.items():
        if not len(values):raise ValueError(f'Aucun pixel valide échantillonné pour la classe {code}.')
        xs.append(values);ys.extend([code]*len(values));ids.extend(pixel_ids)
    return np.concatenate(xs),np.asarray(ys),np.asarray(ids)


@dataclass
class SpectralModel:
    bands:list
    band_names:list
    classes:dict
    arrays:dict
    report:dict

    def probabilities(self,x):
        x=np.asarray(x,dtype='float32')
        a=self.arrays;probabilities=np.zeros((len(x),len(a['codes'])),dtype='float64')
        for root in a['roots']:
            nodes=np.full(len(x),root,dtype='int64')
            for _ in range(int(a['max_depth'][0])+2):
                active=a['left'][nodes]>=0
                if not active.any():break
                ids=np.where(active)[0];current=nodes[ids]
                nodes[ids]=np.where(x[ids,a['feature'][current]]<=a['threshold'][current],a['left'][current],a['right'][current])
            if (a['left'][nodes]>=0).any():raise ValueError('Profondeur du modèle incohérente.')
            probabilities+=a['probability'][nodes]
        return probabilities/len(a['roots'])

    def save(self,directory):
        directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
        if (directory/'model.npz').exists() or (directory/'model.json').exists():raise FileExistsError('Le modèle existe déjà.')
        with open(directory/'model.npz','wb') as handle:np.savez_compressed(handle,**self.arrays)
        save_json(dict(schema='cartomize.classifier.v1',bands=self.bands,band_names=self.band_names,classes=self.classes,report=self.report),directory/'model.json')
        return directory/'model.json'


def load_classifier(path):
    path=Path(path);path=path/'model.json' if path.is_dir() else path
    meta=read_json(path)
    if meta.get('schema')!='cartomize.classifier.v1':raise ValueError('Modèle de classification incompatible.')
    import zipfile
    with zipfile.ZipFile(path.with_suffix('.npz')) as archive:
        if sum(i.file_size for i in archive.infolist())>512*1024**2:raise ValueError('Modèle trop volumineux.')
    with np.load(path.with_suffix('.npz'),allow_pickle=False) as data:arrays={k:data[k] for k in data.files}
    required={'codes','roots','left','right','feature','threshold','probability','max_depth'}
    if set(arrays)!=required:raise ValueError('Modèle incomplet.')
    n=len(arrays['left']);features=len(meta['bands'])
    if n>10_000_000 or not len(arrays['roots']) or arrays['probability'].shape!=(n,len(arrays['codes'])):raise ValueError('Dimensions du modèle invalides.')
    for key in ('left','right'):
        if len(arrays[key])!=n or ((arrays[key]<-1)|(arrays[key]>=n)).any():raise ValueError('Arbre de décision invalide.')
    if ((arrays['roots']<0)|(arrays['roots']>=n)).any() or len(arrays['feature'])!=n:raise ValueError('Racines invalides.')
    for key in ('codes','roots','left','right','feature','max_depth'):
        if arrays[key].ndim!=1 or arrays[key].dtype.kind not in 'iu':raise ValueError('Tableau d’indices invalide.')
    if arrays['max_depth'].shape!=(1,) or not 0<=arrays['max_depth'][0]<=64:raise ValueError('Profondeur du modèle invalide.')
    if arrays['threshold'].shape!=(n,) or not np.isfinite(arrays['threshold']).all():raise ValueError('Seuils invalides.')
    internal=arrays['left']>=0
    if not np.array_equal(internal,arrays['right']>=0):raise ValueError('Branches incohérentes.')
    node_ids=np.arange(n)
    if ((arrays['left'][internal]<=node_ids[internal])|(arrays['right'][internal]<=node_ids[internal])).any():raise ValueError('Cycle dans le modèle.')
    if len(set(arrays['codes']))!=len(arrays['codes']) or set(map(str,arrays['codes']))!=set(meta['classes']):raise ValueError('Classes incohérentes.')
    if (arrays['probability']<0).any() or not np.allclose(arrays['probability'].sum(axis=1),1):raise ValueError('Probabilités invalides.')
    if ((arrays['feature'][internal]<0)|(arrays['feature'][internal]>=features)).any():raise ValueError('Bande du modèle invalide.')
    if not np.isfinite(arrays['probability']).all():raise ValueError('Probabilités invalides.')
    return SpectralModel(meta['bands'],meta['band_names'],{int(k):v for k,v in meta['classes'].items()},arrays,meta['report'])


def fit_classifier(source,training,class_column,*,bands=None,algorithm='random_forest',label_column=None,
                   validation=None,group_column=None,sample_limit=50_000,test_fraction=.25,
                   n_estimators=100,max_depth=24,workers=1,random_state=42,cancel=None,progress=None):
    from sklearn.ensemble import RandomForestClassifier,ExtraTreesClassifier
    from sklearn.model_selection import GroupShuffleSplit
    from sklearn.metrics import confusion_matrix,classification_report,cohen_kappa_score,accuracy_score,balanced_accuracy_score
    if algorithm not in {'random_forest','extra_trees'}:raise ValueError('Algorithme : random_forest ou extra_trees.')
    if not 20<=sample_limit<=2_000_000 or not 1<=n_estimators<=1000 or not 1<=max_depth<=64 or not 1<=workers<=32:raise ValueError('Paramètres d’apprentissage hors limites.')
    if not 0<test_fraction<1:raise ValueError('La proportion de validation doit être comprise entre 0 et 1.')
    data=frame(training)
    if label_column and label_column not in data:raise ValueError('Champ des libellés absent.')
    mapping,classes=_class_table(data,class_column,label_column);evaluation=None;split_kind='unavailable'
    if validation is not None:evaluation=frame(validation);train=data;split_kind='independent_features'
    else:
        if group_column and (group_column not in data or data[group_column].isna().any()):raise ValueError('Groupes de validation manquants.')
        groups=data[group_column] if group_column else np.arange(len(data))
        train=data
        if len(set(groups))>=4:
            splitter=GroupShuffleSplit(n_splits=30,test_size=test_fraction,random_state=random_state)
            for a,b in splitter.split(data,groups=groups):
                if set(data.iloc[a][class_column])==set(mapping.keys()) or set(data.iloc[a][class_column].astype(str))==set(mapping):
                    if set(data.iloc[b][class_column].astype(str))==set(mapping):
                        train=data.iloc[a];evaluation=data.iloc[b];split_kind='held_out_features' if group_column is None else 'held_out_groups';break
    with rasterio.open(source) as src:
        bands=_bands(src,bands);names=[src.descriptions[b-1] or f'band_{b}' for b in bands]
        x,y,train_ids=_sample_features(src,train,class_column,mapping,bands,sample_limit,random_state,cancel,excluded=evaluation)
        if progress:progress(1,4)
        if evaluation is not None:
            xv,yv,validation_ids=_sample_features(src,evaluation,class_column,mapping,bands,sample_limit,random_state+1,cancel)
            if np.intersect1d(train_ids,validation_ids).size:raise ValueError('Apprentissage et validation partagent des pixels ; utiliser des échantillons spatialement distincts.')
    _check_cancel(cancel)
    cls=RandomForestClassifier if algorithm=='random_forest' else ExtraTreesClassifier
    estimator=cls(n_estimators=n_estimators,max_depth=max_depth,n_jobs=workers,random_state=random_state,class_weight={int(code):len(y)/(len(classes)*int((y==code).sum())) for code in classes},warm_start=True)
    # Fit in small tree batches so cancellation can be honored during training.
    for count in range(min(10,n_estimators),n_estimators+10,10):
        _check_cancel(cancel);estimator.n_estimators=min(count,n_estimators);estimator.fit(x,y)
        if progress:progress(2,4)
        if count>=n_estimators:break
    report=dict(algorithm=algorithm,seed=random_state,training_pixels=len(y),training_features=len(train),
                training_source=str(Path(training).resolve()) if isinstance(training,(str,Path)) else 'GeoDataFrame',
                validation_source=str(Path(validation).resolve()) if isinstance(validation,(str,Path)) else None,
                class_column=class_column,label_column=label_column,group_column=group_column,
                parameters=dict(n_estimators=n_estimators,max_depth=max_depth,sample_limit=sample_limit,test_fraction=test_fraction),
                counts={str(c):int((y==c).sum()) for c in estimator.classes_},validation_method=split_kind,
                validation=None,feature_importance=dict(zip(names,estimator.feature_importances_.tolist())),
                note='Validation indépendante nécessaire pour estimer la précision hors des échantillons fournis.')
    if evaluation is not None:
        predictions=estimator.predict(xv);codes=estimator.classes_
        report['validation']=dict(pixels=len(yv),features=len(evaluation),codes=codes.tolist(),
            confusion_matrix=confusion_matrix(yv,predictions,labels=codes).tolist(),accuracy=float(accuracy_score(yv,predictions)),
            balanced_accuracy=float(balanced_accuracy_score(yv,predictions)),kappa=float(cohen_kappa_score(yv,predictions)),
            classes=classification_report(yv,predictions,labels=codes,output_dict=True,zero_division=0))
    roots=[];left=[];right=[];feature=[];threshold=[];probability=[];offset=0;depth=0
    for tree in estimator.estimators_:
        t=tree.tree_;roots.append(offset);depth=max(depth,t.max_depth)
        left.extend(np.where(t.children_left>=0,t.children_left+offset,-1));right.extend(np.where(t.children_right>=0,t.children_right+offset,-1))
        feature.extend(t.feature);threshold.extend(t.threshold)
        values=t.value[:,0,:];probability.extend(values/values.sum(axis=1,keepdims=True));offset+=t.node_count
    arrays=dict(codes=estimator.classes_.astype('int32'),roots=np.asarray(roots,dtype='int64'),left=np.asarray(left,dtype='int64'),
        right=np.asarray(right,dtype='int64'),feature=np.asarray(feature,dtype='int32'),threshold=np.asarray(threshold),
        probability=np.asarray(probability,dtype='float64'),max_depth=np.array([depth]))
    model=SpectralModel(bands,names,classes,arrays,report)
    if not np.allclose(model.probabilities(x[:200]),estimator.predict_proba(x[:200])):raise RuntimeError('La sérialisation du modèle a modifié ses prédictions.')
    if progress:progress(4,4)
    return model


def classify_landcover(source,training,destination,*,class_column='classe',model=None,bands=None,
                       block_size=256,progress=None,cancel=None,**training_options):
    destination=Path(destination).resolve()
    if not 32<=block_size<=1024:raise ValueError('Blocs de classification : 32 à 1 024 pixels.')
    _check_cancel(cancel)
    if model is None:model=fit_classifier(source,training,class_column,bands=bands,cancel=cancel,progress=progress,**training_options)
    elif not isinstance(model,SpectralModel):model=load_classifier(model)
    with new_directory(destination) as work,rasterio.open(source) as src:
        selected=_bands(src,bands or model.bands)
        if len(selected)!=len(model.bands):raise ValueError('Le modèle et le raster doivent avoir les mêmes variables spectrales.')
        names=[src.descriptions[b-1] or f'band_{b}' for b in selected]
        if names!=model.band_names:raise ValueError('Les descriptions des bandes ne correspondent pas au modèle.')
        profile=dict(driver='GTiff',width=src.width,height=src.height,crs=src.crs,transform=src.transform,count=1,
                     tiled=True,blockxsize=256,blockysize=256,compress='lzw',BIGTIFF='IF_SAFER')
        total=math.ceil(src.width/block_size)*math.ceil(src.height/block_size)
        with rasterio.open(work/'classification.tif','w',**profile,dtype='int32',nodata=-2147483648) as dst, \
             rasterio.open(work/'confidence.tif','w',**profile,dtype='float32',nodata=np.nan) as confidence:
            for number,win in enumerate(_windows(src,block_size),1):
                _check_cancel(cancel);values,valid=_spectral(src,selected,win)
                labels=np.full(valid.shape,-2147483648,dtype='int32');prob=np.full(valid.shape,np.nan,dtype='float32')
                if valid.any():
                    probabilities=model.probabilities(values[:,valid].T)
                    labels[valid]=model.arrays['codes'][probabilities.argmax(axis=1)];prob[valid]=probabilities.max(axis=1)
                dst.write(labels,1,window=win);confidence.write(prob,1,window=win)
                if progress:progress(number,total)
            dst.descriptions=('classification',);dst.update_tags(CARTOMIZE_CLASSES=json.dumps(model.classes,ensure_ascii=False),CARTOMIZE_PRODUCT='classification')
            confidence.descriptions=('class_probability',);confidence.update_tags(CARTOMIZE_PRODUCT='classification_confidence')
        model.save(work/'model')
        record=dict(schema='cartomize.classification.v1',source=str(Path(source).resolve()),classes=model.classes,**model.report)
        save_json(record,work/'classification.json');_check_cancel(cancel)
    return destination/'classification.tif'


def cluster_raster(source,destination,*,clusters=6,bands=None,sample_limit=50_000,random_state=42,block_size=256,progress=None,cancel=None):
    """Mini-batch K-means: group IDs have no inferred land-cover meaning."""
    from sklearn.cluster import MiniBatchKMeans
    if not 2<=clusters<=64 or not clusters*10<=sample_limit<=2_000_000 or not 32<=block_size<=1024:raise ValueError('Choisir 2 à 64 groupes, un échantillon suffisant et des blocs de 32 à 1 024 pixels.')
    rng=np.random.default_rng(random_state);reservoir=None;priorities=np.empty(0)
    with rasterio.open(source) as src:
        selected=_bands(src,bands)
        for win in _windows(src,block_size):
            _check_cancel(cancel);values,valid=_spectral(src,selected,win);x=values[:,valid].T
            if not len(x):continue
            reservoir=x if reservoir is None else np.concatenate([reservoir,x]);priorities=np.concatenate([priorities,rng.random(len(x))])
            take=np.argpartition(priorities,min(sample_limit,len(priorities))-1)[:sample_limit];reservoir=reservoir[take];priorities=priorities[take]
        if reservoir is None or len(reservoir)<clusters:raise ValueError('Pixels valides insuffisants.')
        mean=reservoir.mean(axis=0);scale=reservoir.std(axis=0);scale[scale==0]=1
        estimator=MiniBatchKMeans(n_clusters=clusters,random_state=random_state,n_init=3,batch_size=1024)
        estimator.fit((reservoir-mean)/scale);_check_cancel(cancel)
        with new_directory(destination) as work:
            profile=src.profile.copy();profile.update(driver='GTiff',count=1,dtype='uint8',nodata=255,compress='lzw')
            with rasterio.open(work/'clusters.tif','w',**profile) as dst:
                total=math.ceil(src.width/block_size)*math.ceil(src.height/block_size)
                for i,win in enumerate(_windows(src,block_size),1):
                    _check_cancel(cancel);values,valid=_spectral(src,selected,win);result=np.full(valid.shape,255,dtype='uint8')
                    if valid.any():result[valid]=estimator.predict((values[:,valid].T-mean)/scale)+1
                    dst.write(result,1,window=win)
                    if progress:progress(i,total)
                classes={i+1:[f'Groupe spectral {i+1}',to_hex(colormaps['tab20'](i%20))] for i in range(clusters)}
                dst.update_tags(CARTOMIZE_CLASSES=json.dumps(classes),CARTOMIZE_PRODUCT='spectral_clusters')
            save_json(dict(schema='cartomize.clustering.v1',clusters=clusters,bands=selected,mean=mean,scale=scale,
                           centers=estimator.cluster_centers_,sample_pixels=len(reservoir),seed=random_state,
                           interpretation='Les groupes spectraux doivent être interprétés et validés.'),work/'clustering.json')
    return Path(destination).resolve()/'clusters.tif'
