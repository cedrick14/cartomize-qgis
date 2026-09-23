"""Validated raster expressions and bounded, concurrent block processing."""
import ast
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
import math
import os
from pathlib import Path
import time

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window

from .raster import _writer, _band
from .scenes import Band


class ProcessingCancelled(RuntimeError):
    """Cancellation acknowledged before publication of the output file."""


def _valid(value):
    return ~np.ma.getmaskarray(value) & np.isfinite(np.ma.getdata(value))


def _reduce(name, *values):
    arrays=np.ma.stack(np.broadcast_arrays(*[np.ma.getdata(v) for v in values]))
    arrays.mask=np.stack(np.broadcast_arrays(*[~_valid(v) for v in values]))
    return arrays.count(axis=0) if name=="count" else getattr(np.ma,name)(arrays,axis=0)


def _bitand(a,b):
    arrays=[]
    for value in (a,b):
        raw=np.ma.getdata(value); valid=_valid(value)
        if np.any(valid & ((raw!=np.floor(raw)) | (raw<0) | (raw>2**53-1))):
            raise ValueError("bitand requires nonnegative integers no larger than 2**53-1.")
        arrays.append(np.ma.array(np.where(valid,raw,0).astype("int64"),mask=~valid))
    return np.ma.array(np.bitwise_and(arrays[0].data,arrays[1].data),
                       mask=np.ma.getmaskarray(arrays[0])|np.ma.getmaskarray(arrays[1]))


FUNCTIONS={name:getattr(np.ma,name) for name in
           ("sqrt","log","log10","exp","sin","cos","tan","arcsin","arccos","arctan","abs","floor","ceil","minimum","maximum","clip")}
FUNCTIONS.update({"where":np.ma.where,"isvalid":_valid,
                  "coalesce":lambda a,b:np.ma.where(_valid(a),a,b),"bitand":_bitand})
for _name in ("mean","sum","min","max","std","median","count"):
    FUNCTIONS[_name]=lambda *values,_n=_name:_reduce(_n,*values)
ARITY={name:(1,1) for name in FUNCTIONS}
ARITY.update({"minimum":(2,2),"maximum":(2,2),"clip":(3,3),"where":(3,3),
              "coalesce":(2,2),"bitand":(2,2)})
ARITY.update({name:(1,256) for name in ("mean","sum","min","max","std","median","count")})
BIN={ast.Add:np.ma.add,ast.Sub:np.ma.subtract,ast.Mult:np.ma.multiply,
     ast.Div:np.ma.divide,ast.Pow:np.ma.power,ast.Mod:np.ma.mod,
     ast.BitAnd:np.ma.logical_and,ast.BitOr:np.ma.logical_or,ast.BitXor:np.ma.logical_xor}
CMP={ast.Lt:np.ma.less,ast.LtE:np.ma.less_equal,ast.Gt:np.ma.greater,
     ast.GtE:np.ma.greater_equal,ast.Eq:np.ma.equal,ast.NotEq:np.ma.not_equal}


class Expression:
    """Arithmetic, conditions and explicit functions; never executes Python code."""
    def __init__(self,text):
        if not isinstance(text,str) or not text.strip() or len(text)>8192:
            raise ValueError("An expression must contain 1 to 8192 characters.")
        self.text=text
        try:self.tree=ast.parse(text,mode="eval").body
        except (SyntaxError,RecursionError) as exc:raise ValueError("Invalid raster expression.") from exc
        nodes=list(ast.walk(self.tree))
        if len(nodes)>512:raise ValueError("Expression exceeds 512 syntax nodes.")
        self.variables=set()
        self._validate(self.tree)

    def _validate(self,node):
        if isinstance(node,ast.Constant):
            if not isinstance(node.value,(int,float,bool)) or not np.isfinite(float(node.value)):
                raise ValueError("Only finite numerical constants are allowed.")
        elif isinstance(node,ast.Name):
            if node.id.startswith("_"):raise ValueError("Variable names cannot start with an underscore.")
            if node.id not in {"pi","e"}:self.variables.add(node.id)
        elif isinstance(node,ast.BinOp) and type(node.op) in BIN:
            self._validate(node.left);self._validate(node.right)
        elif isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.USub,ast.UAdd,ast.Not,ast.Invert)):
            self._validate(node.operand)
        elif isinstance(node,ast.BoolOp) and isinstance(node.op,(ast.And,ast.Or)):
            for v in node.values:self._validate(v)
        elif isinstance(node,ast.Compare) and all(type(op) in CMP for op in node.ops):
            self._validate(node.left)
            for v in node.comparators:self._validate(v)
        elif isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in FUNCTIONS:
            low,high=ARITY[node.func.id]
            if node.keywords or not low<=len(node.args)<=high:
                raise ValueError(f"Invalid arguments for {node.func.id}.")
            for a in node.args:self._validate(a)
        else:raise ValueError("Unsupported expression syntax: "+type(node).__name__)

    def evaluate(self,variables):
        def visit(n):
            if isinstance(n,ast.Constant):return float(n.value) if not isinstance(n.value,bool) else n.value
            if isinstance(n,ast.Name):return {"pi":np.pi,"e":np.e}.get(n.id,variables.get(n.id))
            if isinstance(n,ast.Call):return FUNCTIONS[n.func.id](*[visit(a) for a in n.args])
            if isinstance(n,ast.BinOp):return BIN[type(n.op)](visit(n.left),visit(n.right))
            if isinstance(n,ast.UnaryOp):
                value=visit(n.operand)
                return -value if isinstance(n.op,ast.USub) else value if isinstance(n.op,ast.UAdd) else np.ma.logical_not(value)
            if isinstance(n,ast.BoolOp):
                result=visit(n.values[0]);op=np.ma.logical_and if isinstance(n.op,ast.And) else np.ma.logical_or
                for value in n.values[1:]:result=op(result,visit(value))
                return result
            if isinstance(n,ast.Compare):
                left=visit(n.left);result=True
                for op,right in zip(n.ops,n.comparators):
                    right=visit(right);result=np.ma.logical_and(result,CMP[type(op)](left,right));left=right
                return result
        with np.errstate(all="ignore"):
            return np.ma.masked_invalid(visit(self.tree))


def _asset(value):
    if isinstance(value,Band):return value,True
    if isinstance(value,(tuple,list)) and len(value)==2:return Band(value[0],index=value[1]),False
    return Band(value),False


def _run_blocks(inputs,destination,names,processor,*,workers=1,block_size=512,
                memory_limit_mb=512,align=False,resampling="nearest",dtype="float32",
                compression="lzw",overwrite=False,progress=None,cancel=None,halo=0,
                metadata=None,execution='threads',scheduler_address=None):
    """Read/write GDAL datasets on one thread; bounded array jobs on workers."""
    if not inputs:raise ValueError("At least one raster input is required.")
    if execution not in {'threads','distributed'}:raise ValueError('execution must be threads or distributed.')
    if scheduler_address and execution!='distributed':raise ValueError('scheduler_address requires distributed execution.')
    if workers=="auto":workers=min(4,os.cpu_count() or 1)
    if not isinstance(workers,int) or not 1<=workers<=32:raise ValueError("workers must be 1..32 or 'auto'.")
    if not isinstance(block_size,int) or not 32<=block_size<=2048:raise ValueError("block_size must be 32..2048.")
    if not np.isfinite(memory_limit_mb) or memory_limit_mb<16:raise ValueError("memory_limit_mb must be at least 16.")
    if dtype not in {"float32","float64"}:raise ValueError("Output dtype must be float32 or float64.")
    if compression not in {"lzw","deflate","none"}:raise ValueError("compression must be lzw, deflate or none.")
    if resampling not in {"nearest","bilinear","cubic","average"}:raise ValueError("Invalid resampling method.")
    assets={name:_asset(value) for name,value in inputs.items()}
    # Conservative working-array estimate; GDAL cache and interpreter excluded.
    bytes_per_pixel=32*(len(assets)+len(names)+8)
    max_pending=workers if workers>1 else 1
    while (block_size+2*halo)**2*bytes_per_pixel*max_pending>memory_limit_mb*1024**2 and block_size>32:
        block_size=max(32,block_size//2)
    estimated=(block_size+2*halo)**2*bytes_per_pixel*max_pending
    if estimated>memory_limit_mb*1024**2:raise ValueError("Memory budget too small for this operation and worker count.")
    def check_cancel():
        if cancel is not None and cancel.is_set():raise ProcessingCancelled("Traitement interrompu.")
    check_cancel();started=time.perf_counter()
    with ExitStack() as stack:
        readers={};datasets={};calibration={};ref=None
        for name,(asset,explicit) in assets.items():
            key=str(Path(asset.path).resolve())
            if key not in datasets:datasets[key]=stack.enter_context(rasterio.open(asset.path))
            src=datasets[key];_band(src,asset.index)
            if src.crs is None:raise ValueError(f"Raster has no CRS: {asset.path}")
            if ref is None:ref=src
            calibration[name]=(asset.scale,asset.offset) if explicit else (src.scales[asset.index-1],src.offsets[asset.index-1])
            same=(src.crs==ref.crs and src.transform==ref.transform and src.shape==ref.shape)
            if not same and not align:raise ValueError("Raster grids differ. Align them first or explicitly set align=True.")
            if not same and asset.nodata is not None:
                raise ValueError("Custom NoData with grid alignment requires prior raster preparation.")
            readers[name]=src if same else stack.enter_context(WarpedVRT(src,crs=ref.crs,transform=ref.transform,
                width=ref.width,height=ref.height,dtype="float64",nodata=np.nan,
                resampling=Resampling[resampling],UNIFIED_SRC_NODATA="NO"))
        profile=dict(driver="GTiff",width=ref.width,height=ref.height,count=len(names),
                     dtype=dtype,crs=ref.crs,transform=ref.transform,nodata=np.nan,
                     tiled=True,blockxsize=256,blockysize=256,BIGTIFF="IF_SAFER")
        if compression!="none":profile.update(compress=compression,predictor=3)
        total=math.ceil(ref.width/block_size)*math.ceil(ref.height/block_size);done=0
        def windows():
            for row in range(0,ref.height,block_size):
                for col in range(0,ref.width,block_size):
                    yield Window(col,row,min(block_size,ref.width-col),min(block_size,ref.height-row))
        def read(window):
            x=max(0,int(window.col_off)-halo);y=max(0,int(window.row_off)-halo)
            right=min(ref.width,int(window.col_off+window.width)+halo)
            bottom=min(ref.height,int(window.row_off+window.height)+halo)
            expanded=Window(x,y,right-x,bottom-y);values={};cache={}
            for name,(asset,_) in assets.items():
                reader=readers[name];key=(id(reader),asset.index)
                if key not in cache:
                    cache[key]=np.ma.masked_invalid(reader.read(asset.index,window=expanded,masked=True).astype("float64"))
                data=cache[key]
                if asset.nodata is not None:data=np.ma.masked_where(data.data==asset.nodata,data)
                scale,offset=calibration[name]
                values[name]=data if scale==1 and offset==0 else np.ma.masked_invalid(data*scale+offset)
            crop=(slice(int(window.row_off)-y,int(window.row_off+window.height)-y),
                  slice(int(window.col_off)-x,int(window.col_off+window.width)-x))
            return values,crop
        from .execution import compute_block,distributed_client,await_result
        def compute(payload):
            check_cancel();return compute_block(processor,payload,names,dtype)
        with _writer(destination,profile,overwrite=overwrite,sources=[a.path for a,_ in assets.values()]) as dst:
            if progress:progress(0,total)
            def write(window,result):
                nonlocal done
                check_cancel();dst.write(result,window=window);done+=1
                if progress:progress(done,total)
            if execution=='distributed':
                with distributed_client(workers,scheduler_address) as client:
                    pending=deque()
                    try:
                        for window in windows():
                            check_cancel()
                            if len(pending)>=max_pending:
                                old,future=pending.popleft()
                                try:write(old,await_result(future,check_cancel))
                                finally:future.release()
                            pending.append((window,client.submit(compute_block,processor,read(window),names,dtype,pure=False)))
                        while pending:
                            old,future=pending.popleft()
                            try:write(old,await_result(future,check_cancel))
                            finally:future.release()
                    finally:
                        if pending:client.cancel([f for _,f in pending])
            elif workers==1:
                for window in windows():check_cancel();write(window,compute(read(window)))
            else:
                with ThreadPoolExecutor(max_workers=workers,thread_name_prefix="cartomize-raster") as executor:
                    pending=deque()
                    try:
                        for window in windows():
                            check_cancel()
                            if len(pending)>=max_pending:
                                old,future=pending.popleft();write(old,future.result())
                            pending.append((window,executor.submit(compute,read(window))))
                        while pending:
                            old,future=pending.popleft();write(old,future.result())
                    finally:
                        for _,future in pending:future.cancel()
            check_cancel();dst.descriptions=tuple(names)
            provenance={name:{"path":str(Path(asset.path).resolve()),"band":asset.index,
                              "scale":calibration[name][0],"offset":calibration[name][1]}
                        for name,(asset,_) in assets.items()}
            dst.update_tags(operation=(metadata or {}).get("operation","raster_calculation"),
                            processing=json.dumps(metadata or {},ensure_ascii=False),
                            inputs=json.dumps(provenance),workers=workers,block_size=block_size,
                            estimated_working_mb=estimated/1024**2,elapsed_seconds=time.perf_counter()-started,
                            alignment=str(bool(align)),resampling=resampling,execution=execution,
                            device=(metadata or {}).get('device','cpu'))
    return Path(destination)


def calculate(expression,inputs,destination,**options):
    """Evaluate one expression or a {output_band: expression} mapping.

    Inputs map variable names to paths, (path, band) pairs or calibrated Band
    objects. Multiple expressions share each block's input reads. GDAL scale
    and offset apply to path/pair inputs; explicit Band values override them.
    Invalid arithmetic becomes NoData. where() propagates the condition mask
    and the selected branch only. mean/sum/min/max/std/median ignore NoData.
    """
    expressions={"result":expression} if isinstance(expression,str) else dict(expression)
    if not expressions or any(not isinstance(k,str) or not k for k in expressions):
        raise ValueError("At least one named expression is required.")
    parsed={k:Expression(v) for k,v in expressions.items()}
    required=set().union(*(e.variables for e in parsed.values()))
    missing=required-set(inputs)
    if missing:raise ValueError("Missing raster variables: "+", ".join(sorted(missing)))
    if any(not isinstance(k,str) or not k.isidentifier() or k in FUNCTIONS or k in {"pi","e"} or k.startswith("_") for k in inputs):
        raise ValueError("Input names must be identifiers distinct from functions and constants.")
    selected={k:v for k,v in inputs.items() if k in required}
    from ._validation import output_path
    output_path(destination,options.get('overwrite',False),[_asset(v)[0].path for v in inputs.values()])
    if not selected and inputs:selected={next(iter(inputs)):next(iter(inputs.values()))}
    device=options.pop('device','cpu')
    if device not in {'cpu','cuda'}:raise ValueError('device must be cpu or cuda.')
    processor=lambda values:[e.evaluate(values) for e in parsed.values()]
    if device=='cuda':
        from .cuda import CudaExpressions
        from .execution import cuda_module
        if options.get('execution','threads')=='threads':cuda_module()
        processor=CudaExpressions(expressions.values())
    return _run_blocks(selected,destination,list(parsed),processor,
                       metadata={"operation":"raster_algebra","expressions":expressions,'device':device},**options)


def reduce_rasters(sources,destination,*,statistic="mean",band=1,min_valid=1,**options):
    """Cell-wise statistics; count returns all counts including zero.

    min_valid filters summary statistics; count requires its default value 1.
    """
    sources=list(sources)
    if statistic not in {"mean","sum","min","max","std","median","count"}:raise ValueError("Invalid statistic.")
    if not sources or not isinstance(min_valid,int) or not 1<=min_valid<=len(sources):raise ValueError("Invalid minimum valid observation count.")
    if statistic=='count' and min_valid!=1:raise ValueError('count reports every observation count; min_valid must be 1.')
    inputs={f"r{i}":value if isinstance(value,(Band,tuple,list)) else (value,band) for i,value in enumerate(sources)}
    args=",".join(inputs)
    expression=f"{statistic}({args})" if statistic=="count" else f"where(count({args}) >= {min_valid}, {statistic}({args}), sqrt(-1))"
    return calculate({statistic:expression},inputs,destination,**options)
