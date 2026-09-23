"""Explicit QGIS renderer transfer with units and unsupported-feature reports."""
from matplotlib.colors import to_hex


def _color(value):
    if not value:return None
    try:
        if ',' in value:
            parts=[float(x)/255 for x in value.split(',')[:4]]
            return to_hex(parts,keep_alpha=len(parts)==4)
        return to_hex(value,keep_alpha=True)
    except (ValueError,TypeError):return None


def _points(value,unit,warnings):
    factors={'MM':72/25.4,'Point':1,'Pixel':72/96,'Inch':72}
    if unit not in factors:
        warnings.append('Dimension en unités cartographiques non transférée : '+str(unit));return None
    try:return float(value)*factors[unit]
    except (TypeError,ValueError):return None


def _symbol(symbol,warnings):
    if symbol is None:return {}
    components=[]
    for layer in symbol.findall('layer'):
        if layer.get('enabled','1')=='0':continue
        props={p.get('k'):p.get('v') for p in layer.findall('prop')}
        props.update({p.get('name'):p.get('value') for p in layer.findall('.//Option') if p.get('name') and p.get('value') is not None})
        kind=layer.get('class');style={}
        if kind not in {'SimpleMarker','SimpleLine','SimpleFill'}:
            warnings.append('Symbole natif non reproduit : '+str(kind));continue
        color=_color(props.get('color') or props.get('line_color'))
        if color:style['color']=color
        outline=_color(props.get('outline_color'))
        if outline and kind!='SimpleLine':style['edgecolor']=outline
        width=props.get('line_width') if kind=='SimpleLine' else props.get('outline_width')
        if width is not None:
            width=_points(width,props.get('line_width_unit' if kind=='SimpleLine' else 'outline_width_unit','MM'),warnings)
            if width is not None:style['linewidth']=width
        pen=props.get('line_style') if kind=='SimpleLine' else props.get('outline_style')
        if pen in {'solid','dash','dot','dash dot','dash dot dot','no'}:
            style['linestyle']={'solid':'-','dash':'--','dot':':','dash dot':'-.','dash dot dot':(0,(3,1,1,1,1,1)),'no':'none'}[pen]
        if kind=='SimpleFill':
            if props.get('style')=='no':style['color']='none'
            elif props.get('style','solid')!='solid':warnings.append('Motif de remplissage non reproduit : '+props['style'])
        if kind=='SimpleMarker':
            marker=props.get('name','circle');markers={'circle':'o','square':'s','diamond':'D','triangle':'^','inverted_triangle':'v','cross':'+','cross2':'x','star':'*'}
            if marker in markers:style['marker']=markers[marker]
            else:warnings.append('Forme ponctuelle non reproduite : '+marker)
            size=_points(props.get('size','2'),props.get('size_unit','MM'),warnings)
            if size is not None:style['markersize']=size**2
            if float(props.get('angle','0'))!=0:warnings.append('Rotation du symbole ponctuel non transférée.')
        if props.get('offset') not in {None,'0','0,0','0,0,0'}:warnings.append('Décalage du symbole non transféré.')
        components.append(style)
    result=dict(components[-1]) if components else {}
    if len(components)>1:
        result={'symbol_layers':components,'color':components[-1].get('color','#56866c')}
        warnings.append('Symbole composite dessiné ; sa légende utilise le composant supérieur.')
    if symbol.get('alpha') is not None:result['alpha']=float(symbol.get('alpha'))
    return result


def layer_style(element):
    options={};warnings=[];renderer=element.find('renderer-v2')
    opacity=element.findtext('layerOpacity')
    if opacity is not None:options['alpha']=float(opacity)
    if renderer is not None:
        symbols={symbol.get('name'):_symbol(symbol,warnings) for symbol in renderer.findall('./symbols/symbol')}
        kind=renderer.get('type');column=renderer.get('attr')
        if kind=='categorizedSymbol':
            classes={};styles={};hidden=[]
            for category in renderer.findall('./categories/category'):
                raw=category.get('value','');value_type=category.get('type','string');value=raw
                if value_type in {'int','uint','longlong','ulonglong','double'}:
                    try:value=float(raw)
                    except ValueError:pass
                if category.get('render','true') in {'false','0'}:hidden.append(value)
                symbol=dict(symbols.get(category.get('symbol'),{}));color=symbol.pop('color',None)
                if color:classes[value]=[category.get('label',str(value)),color];styles[value]=symbol
            if classes:options.update(column=column,classes=classes,categorical=True,category_styles=styles,hidden_categories=hidden)
            else:warnings.append('Catégories sans couleurs transférables.')
        elif kind=='graduatedSymbol':
            ranges=[]
            for item in renderer.findall('./ranges/range'):
                symbol=dict(symbols.get(item.get('symbol'),{}));color=symbol.pop('color',None)
                if color:ranges.append(dict(lower=float(item.get('lower')),upper=float(item.get('upper')),label=item.get('label',''),color=color,style=symbol,visible=item.get('render','true') not in {'false','0'}))
            if ranges:options.update(column=column,ranges=sorted(ranges,key=lambda r:r['lower']))
            else:warnings.append('Classes graduées sans couleurs transférables.')
        elif kind=='singleSymbol':
            symbol=dict(next(iter(symbols.values()),{}));alpha=symbol.pop('alpha',1.)
            options.update(symbol);options['alpha']=options.get('alpha',1.)*alpha
        else:warnings.append('Rendu natif à conserver dans QGIS : '+str(kind))
        if renderer.find('.//data_defined_properties') is not None:
            active=renderer.findall(".//Option[@name='active'][@value='true']")
            if active:warnings.append('Propriétés définies par les données non évaluées hors du moteur QGIS.')
    raster=element.find('./pipe/rasterrenderer')
    if raster is not None:
        kind=raster.get('type')
        if kind=='paletted':
            options['classes']={float(i.get('value')):[i.get('label',i.get('value')),_color(i.get('color'))] for i in raster.findall('./colorPalette/paletteEntry')}
            options['band']=int(raster.get('band','1'))
        elif kind=='multibandcolor':options['rgb']=[int(raster.get(k)) for k in ('redBand','greenBand','blueBand')]
        elif kind=='singlebandgray':
            options.update(band=int(raster.get('grayBand','1')),cmap='gray_r' if raster.get('gradient')=='WhiteToBlack' else 'gray')
            contrast=raster.find('contrastEnhancement')
            if contrast is not None:
                low=float(contrast.findtext('minValue','0'));high=float(contrast.findtext('maxValue','255'))
                if high>low:options['raster_range']=[low,high]
        elif kind=='singlebandpseudocolor':
            shader=raster.find('./rastershader/colorrampshader')
            if shader is not None:
                mode={'INTERPOLATED':'linear','DISCRETE':'discrete','EXACT':'exact'}.get(shader.get('colorRampType','INTERPOLATED'))
                items=[]
                for item in shader.findall('item'):
                    value=float(item.get('value'));color=_color(item.get('color'))
                    if color:
                        from matplotlib.colors import to_rgba
                        rgba=to_rgba(color);opacity=float(item.get('alpha','255'))/255
                        items.append(dict(value=value,label=item.get('label',str(value)),color=to_hex((*rgba[:3],rgba[3]*opacity),keep_alpha=True)))
                if mode and items:options.update(band=int(raster.get('band','1')),raster_ramp=dict(type=mode,items=sorted(items,key=lambda i:i['value']),clip=shader.get('clip','0')=='1'))
                else:warnings.append('Rampe de couleurs raster non transférable.')
        else:warnings.append('Rendu raster natif non reproduit : '+str(kind))
        if raster.get('opacity') is not None:options['alpha']=float(raster.get('opacity'))
        if kind=='multibandcolor' and raster.find('redContrastEnhancement') is not None:warnings.append('L’étirement RVB utilise les percentiles Cartomize ; les contrastes natifs restent à régler.')
    settings=element.find('./labeling/settings/text-style')
    if settings is not None and element.get('labelsEnabled','1')!='0':
        if settings.get('isExpression','0')=='0':options['labels']=settings.get('fieldName')
        else:warnings.append('Expression d’étiquette non évaluée hors du moteur QGIS.')
    return options,list(dict.fromkeys(warnings))
