"""Translate supported QGIS symbols explicitly, retaining unsupported cases."""
from matplotlib.colors import to_hex


def _color(value):
    if not value:return None
    try:
        if ',' in value:
            parts=[float(x)/255 for x in value.split(',')[:4]]
            return to_hex(parts,keep_alpha=len(parts)==4)
        return to_hex(value,keep_alpha=True)
    except (ValueError,TypeError):return None


def layer_style(element):
    options={};warnings=[];renderer=element.find('renderer-v2')
    opacity=element.findtext('layerOpacity')
    if opacity is not None:options['alpha']=float(opacity)
    symbols={}
    if renderer is not None:
        for symbol in renderer.findall('./symbols/symbol'):
            layers=symbol.findall('layer')
            if len(layers)!=1:warnings.append('Symbole composite : seule la couleur principale est transférée.')
            props={}
            for layer in layers[:1]:
                props.update({p.get('k'):p.get('v') for p in layer.findall('prop')})
                props.update({p.get('name'):p.get('value') for p in layer.findall('.//Option') if p.get('name')})
                if layer.get('class') not in {'SimpleMarker','SimpleLine','SimpleFill'}:
                    warnings.append('Symbole natif non reproduit : '+str(layer.get('class')))
            symbols[symbol.get('name')]=props
        kind=renderer.get('type');column=renderer.get('attr')
        if kind=='categorizedSymbol':
            classes={}
            for category in renderer.findall('./categories/category'):
                if category.get('render','true')=='false':warnings.append('Catégorie masquée dans QGIS : vérifier la visibilité lors du transfert.')
                value=category.get('value','');value_type=category.get('type','string')
                if value_type in {'int','uint','longlong','ulonglong','double'}:
                    try:value=float(value)
                    except ValueError:pass
                props=symbols.get(category.get('symbol'),{})
                color=_color(props.get('color') or props.get('line_color'))
                if color:classes[value]=[category.get('label',str(value)),color]
            if classes:options.update(column=column,classes=classes,categorical=True)
            else:warnings.append('Catégories sans couleurs transférables.')
        elif kind=='singleSymbol':
            props=next(iter(symbols.values()),{});color=_color(props.get('color') or props.get('line_color'))
            if color:options['color']=color
            outline=_color(props.get('outline_color'))
            if outline:options['edgecolor']=outline
        else:warnings.append('Rendu natif à conserver dans QGIS : '+str(kind))
    raster=element.find('./pipe/rasterrenderer')
    if raster is not None:
        kind=raster.get('type')
        if kind=='paletted':
            options['classes']={float(i.get('value')):[i.get('label',i.get('value')),_color(i.get('color'))] for i in raster.findall('./colorPalette/paletteEntry')}
            options['band']=int(raster.get('band','1'))
        elif kind=='multibandcolor':options['rgb']=[int(raster.get(k)) for k in ('redBand','greenBand','blueBand')]
        elif kind!='singlebandgray':warnings.append('Rendu raster natif non reproduit : '+str(kind))
        if raster.get('opacity') is not None:options['alpha']=float(raster.get('opacity'))
    settings=element.find('./labeling/settings/text-style')
    if settings is not None and element.get('labelsEnabled','1')!='0':
        if settings.get('isExpression','0')=='0':options['labels']=settings.get('fieldName')
        else:warnings.append('Expression d’étiquetage à évaluer dans QGIS.')
    if element.find('diagramrenderer') is not None:warnings.append('Diagramme natif non transféré.')
    return options,list(dict.fromkeys(warnings))
