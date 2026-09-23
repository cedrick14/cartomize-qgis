"""Measured text fitting and deterministic cartographic label placement."""
import math
from matplotlib.font_manager import FontProperties
from matplotlib import patheffects


def wrap_measured(text,width,renderer,font):
    lines=[]
    def fits(value):return renderer.get_text_width_height_descent(value,font,False)[0]<=width
    for paragraph in str(text).split('\n'):
        current=''
        for word in paragraph.split():
            if current and not fits(current+' '+word):lines.append(current);current=''
            while word and not fits(word):
                length=1
                while length<len(word) and fits(word[:length+1]):length+=1
                if current:lines.append(current);current=''
                lines.append(word[:length]);word=word[length:]
            if word:current=(current+' '+word).strip()
        lines.append(current)
    return '\n'.join(lines)


def fit_text(ax,text,*,fontsize=9,minimum=6,weight='normal',color='#182d35',rotation=0):
    renderer=ax.figure.canvas.get_renderer();width=ax.bbox.width*.98;height=ax.bbox.height*.98
    artist=ax.text(.01,.99,'',ha='left',va='top',color=color,weight=weight,rotation=rotation,clip_on=False)
    fitted=False
    size=max(minimum,float(fontsize))
    while size>=minimum:
        font=FontProperties(size=size,weight=weight)
        if size>minimum and any(renderer.get_text_width_height_descent(word,font,False)[0]>width for word in str(text).split()):
            size-=.5;continue
        wrapped=wrap_measured(text,width,renderer,font)
        artist.set_text(wrapped);artist.set_fontsize(size)
        bbox=artist.get_window_extent(renderer)
        if bbox.width<=width+1 and bbox.height<=height+1:fitted=True;break
        size-=.5
    return artist,dict(text=str(text),fitted=fitted,fontsize=artist.get_fontsize(),lines=artist.get_text().count('\n')+1)


def place_labels(ax,annotations,*,zorder=100,fontsize=7,obstacles=()):
    """Try 24 positions at two font sizes using a spatial occupancy grid."""
    renderer=ax.figure.canvas.get_renderer();frame=ax.get_window_extent();grid={};boxes=[];placed=0;omitted=[]
    cell_size=40
    def cells(box):
        for x in range(math.floor(box.x0/cell_size),math.floor(box.x1/cell_size)+1):
            for y in range(math.floor(box.y0/cell_size),math.floor(box.y1/cell_size)+1):yield x,y
    from matplotlib.transforms import Bbox
    obstacle_boxes=[];obstacle_grid={}
    for x,y,radius_points in obstacles:
        px,py=ax.transData.transform((x,y));radius=radius_points*ax.figure.dpi/72
        box=Bbox.from_extents(px-radius,py-radius,px+radius,py+radius);idx=len(obstacle_boxes);obstacle_boxes.append(box)
        for cell in cells(box):obstacle_grid.setdefault(cell,set()).add(idx)
    candidates=[(dx*distance,dy*distance) for distance in (4,10,18) for dx,dy in [(1,1),(-1,1),(1,-1),(-1,-1),(0,1),(0,-1),(1,0),(-1,0)]]
    for x,y,label in annotations:
        px,py=ax.transData.transform((x,y))
        if not frame.contains(px,py):continue
        artist=ax.annotate(label,(x,y),xytext=(4,4),textcoords='offset points',fontsize=fontsize,color='#182d35',
            zorder=zorder,clip_on=True,path_effects=[patheffects.withStroke(linewidth=2,foreground='white')])
        success=False
        for size in (fontsize,max(6,fontsize-.75)):
            artist.set_fontsize(size)
            for dx,dy in candidates:
                artist.set_position((dx,dy));artist.set_ha('left' if dx>0 else 'right' if dx<0 else 'center');artist.set_va('bottom' if dy>0 else 'top' if dy<0 else 'center')
                box=artist.get_window_extent(renderer).expanded(1.04,1.08)
                if box.x0<frame.x0+1 or box.x1>frame.x1-1 or box.y0<frame.y0+1 or box.y1>frame.y1-1:continue
                ids=set().union(*(grid.get(cell,set()) for cell in cells(box)))
                if any(box.overlaps(boxes[i]) for i in ids):continue
                obstacles_here=set().union(*(obstacle_grid.get(cell,set()) for cell in cells(box)))
                if any(box.overlaps(obstacle_boxes[i]) for i in obstacles_here):continue
                index=len(boxes);boxes.append(box)
                for cell in cells(box):grid.setdefault(cell,set()).add(index)
                success=True;placed+=1;break
            if success:break
        if not success:artist.remove();omitted.append(label)
    return dict(total=len(annotations),placed=placed,omitted=omitted,boxes=[list(b.extents) for b in boxes],obstacle_count=len(obstacle_boxes))
