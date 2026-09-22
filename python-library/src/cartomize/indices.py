"""Spectral index definitions, explicit band correspondence and batch evaluation."""
import ast
from dataclasses import dataclass, field
import re
import rasterio
from .algebra import Expression, calculate
from .scenes import Band


@dataclass(frozen=True)
class IndexDefinition:
    name: str
    title: str
    formula: str
    bands: tuple[str,...]
    parameters: dict[str,float]=field(default_factory=dict)
    reference: str=""
    domain: str=""


_REGISTRY={}


def register_index(name,formula,*,bands,title=None,parameters=None,reference="",domain="",replace=False):
    """Register an index for the current process; use an explicit publication reference."""
    name=name.upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*",name):raise ValueError("Invalid index identifier.")
    if name in _REGISTRY and not replace:raise ValueError(f"Index already registered: {name}")
    parsed=Expression(formula);parameters=dict(parameters or {});bands=tuple(bands)
    if not bands or len(set(bands))!=len(bands) or set(bands)&set(parameters):raise ValueError("Bands and parameters must be distinct.")
    if parsed.variables != set(bands)|set(parameters):raise ValueError("Declare every formula variable as a band or parameter.")
    for value in parameters.values():Expression(repr(float(value)))
    _REGISTRY[name]=IndexDefinition(name,title or name,formula,bands,parameters,reference,domain)
    return _REGISTRY[name]


def list_indices():
    """Return serializable index definitions, including formulas and references."""
    from dataclasses import asdict
    return [asdict(v) for v in _REGISTRY.values()]


def get_index(name):
    try:return _REGISTRY[name.upper()]
    except KeyError:raise ValueError(f"Unknown spectral index: {name}") from None


def _formula(definition,parameters):
    unknown=set(parameters)-set(definition.parameters)
    if unknown:raise ValueError(f"Unknown parameters for {definition.name}: {sorted(unknown)}")
    params={**definition.parameters,**parameters}
    class Constants(ast.NodeTransformer):
        def visit_Name(self,node):
            return ast.copy_location(ast.Constant(float(params[node.id])),node) if node.id in params else node
    text=ast.unparse(Constants().visit(ast.parse(definition.formula,mode="eval")))
    Expression(text)
    return text


def spectral_indices(source,destination,indices=("NDVI",),*,band_map=None,parameters=None,
                     scale=None,offset=None,**options):
    """Compute several indices in one pass into named output bands.

    Semantic descriptions are used only if unique. Otherwise supply band_map
    (e.g. red=3, nir=4). Reflectance with its physical scale is required for
    indices containing additive constants (EVI, SAVI, etc.). No sensor is
    inferred from band position. Custom multi-file indices use calculate().
    """
    if isinstance(indices,str):indices=[indices]
    definitions=[get_index(name) for name in indices]
    if not definitions or len({d.name for d in definitions})!=len(definitions):raise ValueError("Choose distinct spectral indices.")
    parameters=parameters or {}
    if set(parameters)-{d.name for d in definitions}:raise ValueError("Parameter keys must match selected index names.")
    required=set().union(*(d.bands for d in definitions));mapping=dict(band_map or {})
    with rasterio.open(source) as src:
        if src.tags().get('CARTOMIZE_PRODUCT')=='display_rgba':
            raise ValueError('Use the scientific multiband raster, not the display RGBA product, for spectral indices.')
        labels=[(d or src.tags(i).get("semantic_name","")).casefold() for i,d in enumerate(src.descriptions,1)]
        for name in required:
            if name not in mapping:
                matches=[i+1 for i,d in enumerate(labels) if d==name]
                if len(matches)!=1:raise ValueError(f"Declare the band number for {name}.")
                mapping[name]=matches[0]
        if len({mapping[name] for name in required})!=len(required):
            raise ValueError('Assign distinct raster bands to distinct spectral names.')
        inputs={}
        for name in sorted(required):
            index=mapping[name]
            if not isinstance(index,int) or not 1<=index<=src.count:raise ValueError(f"Invalid band number for {name}.")
            inputs[name]=(source,index) if scale is None and offset is None else Band(source,index=index,
                scale=src.scales[index-1] if scale is None else scale,
                offset=src.offsets[index-1] if offset is None else offset)
    expressions={d.name:_formula(d,parameters.get(d.name,{})) for d in definitions}
    return calculate(expressions,inputs,destination,**options)


# Published formulas; each definition records its source and parameter defaults.
for _record in [
    ("NDVI","Indice de végétation par différence normalisée","(nir-red)/(nir+red)",("nir","red"),{},"https://ntrs.nasa.gov/citations/19740022614","Végétation"),
    ("EVI","Indice de végétation amélioré","g*(nir-red)/(nir+C1*red-C2*blue+L)",("nir","red","blue"),{"g":2.5,"C1":6.,"C2":7.5,"L":1.},"https://doi.org/10.1016/S0034-4257(96)00112-5","Végétation"),
    ("EVI2","Indice de végétation amélioré à deux bandes","g*(nir-red)/(nir+2.4*red+L)",("nir","red"),{"g":2.5,"L":1.},"https://doi.org/10.1016/j.rse.2008.06.006","Végétation"),
    ("SAVI","Indice de végétation ajusté au sol","(1+L)*(nir-red)/(nir+red+L)",("nir","red"),{"L":.5},"https://doi.org/10.1016/0034-4257(88)90106-X","Végétation"),
    ("OSAVI","Indice de végétation ajusté au sol optimisé","(nir-red)/(nir+red+0.16)",("nir","red"),{},"https://doi.org/10.1016/0034-4257(95)00186-7","Végétation"),
    ("MSAVI","Indice de végétation ajusté au sol modifié","(2*nir+1-sqrt((2*nir+1)**2-8*(nir-red)))/2",("nir","red"),{},"https://doi.org/10.1016/0034-4257(94)90134-1","Végétation"),
    ("GNDVI","Indice de végétation normalisé utilisant le vert","(nir-green)/(nir+green)",("nir","green"),{},"https://doi.org/10.1016/S0034-4257(96)00072-7","Végétation"),
    ("NDRE","Indice normalisé du red edge","(nir-rededge1)/(nir+rededge1)",("nir","rededge1"),{},"https://doi.org/10.1016/1011-1344(93)06963-4","Végétation"),
    ("NDWI","Indice d’eau par différence normalisée (McFeeters)","(green-nir)/(green+nir)",("green","nir"),{},"https://doi.org/10.1080/01431169608948714","Eau"),
    ("MNDWI","Indice d’eau par différence normalisée modifié","(green-swir1)/(green+swir1)",("green","swir1"),{},"https://doi.org/10.1080/01431160600589179","Eau"),
    ("NDMI","Indice d’humidité par différence normalisée","(nir-swir1)/(nir+swir1)",("nir","swir1"),{},"https://doi.org/10.1016/S0034-4257(01)00318-2","Humidité"),
    ("NBR","Rapport de brûlure normalisé","(nir-swir2)/(nir+swir2)",("nir","swir2"),{},"https://doi.org/10.3133/ofr0211","Incendies"),
    ("NBR2","Rapport de brûlure normalisé à deux bandes SWIR","(swir1-swir2)/(swir1+swir2)",("swir1","swir2"),{},"https://www.usgs.gov/landsat-missions/landsat-normalized-burn-ratio-2","Incendies"),
    ("NDBI","Indice du bâti par différence normalisée","(swir1-nir)/(swir1+nir)",("swir1","nir"),{},"https://doi.org/10.1080/01431160304987","Bâti"),
    ("BSI","Indice de sol nu","((swir1+red)-(nir+blue))/((swir1+red)+(nir+blue))",("swir1","red","nir","blue"),{},"https://github.com/awesome-spectral-indices/awesome-spectral-indices/blob/main/output/spectral-indices-dict.json","Sol"),
    ("ARVI","Indice de végétation résistant aux effets atmosphériques","(nir-(red-gamma*(red-blue)))/(nir+(red-gamma*(red-blue)))",("nir","red","blue"),{"gamma":1.},"https://doi.org/10.1109/36.134076","Végétation"),
    ("VARI","Indice de végétation visible résistant aux effets atmosphériques","(green-red)/(green+red-blue)",("green","red","blue"),{},"https://doi.org/10.1016/S0034-4257(01)00289-9","Végétation"),
    ("SR","Rapport spectral simple","nir/red",("nir","red"),{},"https://doi.org/10.2307/1936256","Végétation"),
]:
    _name,_title,_expr,_bands,_params,_ref,_domain=_record
    register_index(_name,_expr,bands=_bands,title=_title,parameters=_params,reference=_ref,domain=_domain)
