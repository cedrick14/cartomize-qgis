"""Metric terrain derivatives and arbitrary convolution on overlapping blocks."""
import numpy as np
import rasterio
from scipy.ndimage import correlate,minimum_filter,maximum_filter
from .algebra import _run_blocks
from ._validation import linear_factor


def convolve(source,destination,kernel,*,band=1,normalize=False,**options):
    """Discrete convolution; all nonzero-kernel neighbours must be valid.

    Normalization divides by the kernel sum. No implicit filling at NoData or
    image edges; halos guarantee identical results at block boundaries.
    """
    kernel=np.asarray(kernel,dtype='float64')
    if kernel.ndim!=2 or any(n%2!=1 or not 1<=n<=127 for n in kernel.shape) or not np.isfinite(kernel).all() or not np.any(kernel):raise ValueError('Le noyau doit être une matrice finie de dimensions impaires (1 à 127).')
    if normalize:
        if np.isclose(kernel.sum(),0):raise ValueError('Un noyau de somme nulle ne peut pas être normalisé.')
        kernel=kernel/kernel.sum()
    def process(values):
        data=values['source'];valid=~np.ma.getmaskarray(data)
        # scipy correlate is used with a reversed kernel for true convolution.
        result=correlate(np.where(valid,data.data,0),kernel[::-1,::-1],mode='constant',cval=0)
        count=correlate(valid.astype('int32'),(kernel[::-1,::-1]!=0).astype('int32'),mode='constant',cval=0)
        return [np.ma.array(result,mask=count!=np.count_nonzero(kernel))]
    return _run_blocks({'source':(source,band)},destination,['convolution'],process,halo=max(kernel.shape)//2,metadata=dict(operation='convolution',kernel=kernel.tolist(),normalize=normalize),**options)


def terrain(source,destination,*,products=('slope','aspect','hillshade'),band=1,z_factor=1.,azimuth=315.,altitude=45.,**options):
    """Horn 3×3 slope/aspect/hillshade; TPI, Riley TRI and roughness.

    Horizontal coordinates must be projected. z_factor converts calibrated
    elevation values to metres. Slope is degrees; aspect is downslope azimuth
    clockwise from grid north (flat=-1); hillshade is in [0,255].
    """
    allowed={'slope','aspect','hillshade','tpi','tri','roughness'};products=[products] if isinstance(products,str) else list(products)
    if not products or len(set(products))!=len(products) or set(products)-allowed:raise ValueError('Dérivée de terrain inconnue ou dupliquée.')
    if not np.isfinite(z_factor) or z_factor<=0 or not np.isfinite(azimuth) or not 0<=altitude<=90:raise ValueError('Paramètres altimétriques ou solaires invalides.')
    with rasterio.open(source) as src:
        factor=linear_factor(src.crs);transform=src.transform
        if transform.b or transform.d or transform.a<=0 or transform.e>=0:raise ValueError('Reprojeter le MNT sur une grille orientée au nord.')
        dx=transform.a*factor;dy=-transform.e*factor
    east=np.array([[-1,0,1],[-2,0,2],[-1,0,1]],dtype=float)/(8*dx)
    north=np.array([[1,2,1],[0,0,0],[-1,-2,-1]],dtype=float)/(8*dy)
    def process(values):
        source=values['dem'];valid=~np.ma.getmaskarray(source);z=np.where(valid,source.data*z_factor,0)
        count=correlate(valid.astype('int32'),np.ones((3,3),dtype='int32'),mode='constant',cval=0);mask=count<9
        gx=correlate(z,east,mode='constant');gy=correlate(z,north,mode='constant');gradient=np.hypot(gx,gy)
        result={}
        if 'slope' in products:result['slope']=np.degrees(np.arctan(gradient))
        if 'aspect' in products:result['aspect']=np.where(gradient<1e-12,-1,(np.degrees(np.arctan2(-gx,-gy))+360)%360)
        if 'hillshade' in products:
            az=np.radians(azimuth);alt=np.radians(altitude)
            result['hillshade']=255*np.clip((-gx*np.sin(az)*np.cos(alt)-gy*np.cos(az)*np.cos(alt)+np.sin(alt))/np.sqrt(1+gradient**2),0,1)
        if 'tpi' in products:result['tpi']=z-(correlate(z,np.ones((3,3)),mode='constant')-z)/8
        if 'tri' in products:
            total=np.zeros_like(z)
            padded=np.pad(z,1,mode='constant')
            for y in range(3):
                for x in range(3):
                    if (x,y)!=(1,1):total+=(padded[y:y+z.shape[0],x:x+z.shape[1]]-z)**2
            result['tri']=np.sqrt(total)
        if 'roughness' in products:result['roughness']=maximum_filter(z,3)-minimum_filter(z,3)
        return [np.ma.array(result[p],mask=mask) for p in products]
    return _run_blocks({'dem':(source,band)},destination,products,process,halo=1,metadata=dict(operation='terrain',method='Horn 1981 / Riley 1999',z_factor=z_factor,azimuth=azimuth,altitude=altitude,aspect_reference='grid_north',flat_aspect=-1),**options)
