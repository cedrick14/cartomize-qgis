"""Optional execution engines, with bounded queues and explicit capabilities."""
from contextlib import contextmanager
from importlib.util import find_spec
import os
import time
import numpy as np


def cuda_module():
    try:
        import cupy
        if cupy.cuda.runtime.getDeviceCount()<1:raise RuntimeError('Aucun périphérique CUDA.')
        return cupy
    except Exception as exc:
        raise RuntimeError('Calcul CUDA indisponible. Installer une version CuPy compatible avec le pilote NVIDIA et vérifier le GPU. Aucun remplacement automatique par le CPU.') from exc


def execution_capabilities():
    report={'threads':{'available':True},'distributed':{'available':find_spec('distributed') is not None},
            'cuda':{'available':False},'pid':os.getpid()}
    try:
        cp=cuda_module();properties=cp.cuda.runtime.getDeviceProperties(cp.cuda.Device().id)
        name=properties['name'];name=name.decode() if isinstance(name,bytes) else str(name)
        report['cuda']=dict(available=True,name=name,devices=cp.cuda.runtime.getDeviceCount(),memory_bytes=int(properties['totalGlobalMem']))
    except RuntimeError as exc:report['cuda']['reason']=str(exc)
    return report


def compute_block(processor,payload,names,dtype):
    """Worker payload contains arrays and an operator, never GDAL handles."""
    values,crop=payload;shape=next(iter(values.values())).shape
    results=processor(values)
    if len(results)!=len(names):raise ValueError('Processor output count differs from band names.')
    output=[]
    for result in results:
        result=np.ma.asarray(result,dtype='float64');data=np.broadcast_to(result.filled(np.nan),shape)[crop]
        with np.errstate(over='ignore',invalid='ignore'):data=data.astype(dtype)
        output.append(np.where(np.isfinite(data),data,np.nan))
    return np.stack(output)


def await_result(future,check_cancel):
    while not future.done():check_cancel();time.sleep(.02)
    check_cancel();return future.result()


@contextmanager
def distributed_client(workers,address=None):
    try:from distributed import Client,LocalCluster
    except ImportError as exc:raise RuntimeError('Installer cartomize[distributed] pour le calcul distribué.') from exc
    if address:
        # Connection to a cluster explicitly selected by the caller. Treat it as
        # trusted infrastructure: Dask transports Python operators and input arrays.
        with Client(address,set_as_default=False,timeout='15s') as client:yield client
    else:
        with LocalCluster(n_workers=workers,threads_per_worker=1,processes=True,
                          host='127.0.0.1',dashboard_address=None,memory_limit=0) as cluster:
            with Client(cluster,set_as_default=False) as client:yield client
