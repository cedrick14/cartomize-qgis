"""Numerical and process-level checks for optional computation engines."""
import json,os,threading
from pathlib import Path
import numpy as np
import pytest
import rasterio
import cartomize as cm
from cartomize.algebra import Expression,ProcessingCancelled
from cartomize.cuda import evaluate_array


FORMULAS=['a+b','a-b','a*b','a/b','a**b','a%b','-a','~a','a and b','a or b',
          'a < b <= 8','(a > b) | (a == 0)','(a != b) & (b >= 0)',
          'where(a > 0,a,b)','coalesce(a,b)','isvalid(a)','sqrt(a)','log(a)','log10(a)',
          'exp(a)','sin(a)','cos(a)','tan(a)','arcsin(a)','arccos(a)','arctan(a)',
          'abs(a)','floor(a)','ceil(a)','minimum(a,b)','maximum(a,b)','clip(a,0,4)',
          'mean(a,b)','sum(a,b)','min(a,b)','max(a,b)','std(a,b)','median(a,b)','count(a,b)','pi+e']


@pytest.mark.parametrize('formula',FORMULAS)
def test_cuda_array_semantics_match_masked_reference(formula):
    a=np.ma.array([[-2.,-1,0,1,2,3,4,5]],mask=[[0,0,0,0,1,0,0,1]])
    b=np.ma.array([[.5,1,0,2,3,0,8,4]],mask=[[0,0,0,0,0,1,0,1]])
    with np.errstate(all='ignore'):
        expected=Expression(formula).evaluate({'a':a,'b':b});data,mask=evaluate_array(formula,{'a':a,'b':b},np)
    np.testing.assert_array_equal(np.ma.getmaskarray(expected),mask)
    np.testing.assert_allclose(np.ma.asarray(expected,dtype=float).filled(np.nan),np.ma.array(data,mask=mask,dtype=float).filled(np.nan),equal_nan=True)


def test_cuda_bitwise_validation():
    a=np.ma.array([0,3,8,2.5],mask=[0,0,0,1]);b=np.ma.array([1,1,2,0])
    raw,mask=evaluate_array('bitand(a,b)',dict(a=a,b=b),np)
    np.testing.assert_array_equal(raw[:3],[0,1,0]);assert mask[-1]
    with pytest.raises(ValueError,match='nonnegative'):evaluate_array('bitand(a,b)',dict(a=np.array([-1]),b=b),np)


@pytest.fixture(scope='module')
def cluster():
    distributed=pytest.importorskip('distributed')
    with distributed.LocalCluster(n_workers=2,threads_per_worker=1,processes=True,host='127.0.0.1',dashboard_address=None,memory_limit=0) as server:
        with distributed.Client(server) as client:
            pids=client.run(os.getpid);assert len(set(pids.values()))==2 and os.getpid() not in pids.values()
            yield server.scheduler_address,client


@pytest.mark.parametrize('operation',['calculate','indices','reduce','focal','terrain','convolve'])
def test_distributed_operators_match_threads(cluster,write_raster,tmp_path,operation):
    y,x=np.mgrid[:74,:83];data=(30+y+x*2).astype('float32');data[30:35,29:34]=-9999
    source=write_raster('source.tif',np.stack([data,data*2]));params={'source':str(source)}
    if operation=='calculate':params={'expression':{'ratio':'b/a','fill':'coalesce(a,0)'},'inputs':{'a':[str(source),1],'b':[str(source),2]}}
    elif operation=='indices':params.update(indices=['NDVI'],band_map={'red':1,'nir':2})
    elif operation=='reduce':params={'sources':[str(source),str(source)],'statistic':'mean'}
    elif operation=='terrain':params['products']=['slope','aspect','hillshade','tri','tpi','roughness']
    elif operation=='focal':params.update(size=5,statistic='std')
    else:params.update(kernel=[[0,1,0],[1,4,1],[0,1,0]],normalize=True)
    a=cm.execute_operation(operation,params,tmp_path/'cpu',workers=2,block_size=32)
    b=cm.execute_operation(operation,params,tmp_path/'distributed',workers=2,block_size=32,execution='distributed',scheduler_address=cluster[0])
    with rasterio.open(a['primary']) as left,rasterio.open(b['primary']) as right:
        np.testing.assert_allclose(left.read(),right.read(),equal_nan=True,atol=1e-6)
        assert right.tags()['execution']=='distributed' and right.transform==left.transform


def test_distributed_local_cluster_chain_and_cancellation(cluster,write_raster,tmp_path):
    source=write_raster('input.tif',np.ones((70,70),dtype='float32'))
    plan=cm.processing_plan([dict(id='double',operation='calculate',parameters={'expression':'a*2','inputs':{'a':str(source)}})])
    report=json.loads(cm.run_plan(plan,tmp_path/'local',workers=2,block_size=32,execution='distributed').read_text())
    with rasterio.open(report['results']['double']) as src:assert (src.read(1)==2).all()
    event=threading.Event()
    with pytest.raises(ProcessingCancelled):
        cm.calculate('a*3',{'a':source},tmp_path/'cancelled.tif',workers=2,block_size=32,execution='distributed',scheduler_address=cluster[0],cancel=event,progress=lambda done,total:event.set() if done else None)
    assert not (tmp_path/'cancelled.tif').exists() and cluster[1].status=='running'


def test_unavailable_cuda_fails_without_cpu_fallback(write_raster,tmp_path):
    if cm.execution_capabilities()['cuda']['available']:pytest.skip('CUDA available: hardware parity test covers this machine')
    source=write_raster('input.tif',np.ones((40,40),dtype='float32'))
    with pytest.raises(RuntimeError,match='CUDA indisponible'):cm.calculate('a*2',{'a':source},tmp_path/'gpu.tif',device='cuda')
    assert not (tmp_path/'gpu.tif').exists()


@pytest.mark.skipif(not cm.execution_capabilities()['cuda']['available'],reason='No CUDA device/runtime: hardware validation required')
def test_real_cuda_raster_parity(write_raster,tmp_path):
    rng=np.random.default_rng(10);source=write_raster('input.tif',rng.uniform(-2,4,(2,83,74)).astype('float32'))
    expressions={str(i):s for i,s in enumerate(FORMULAS)};inputs={'a':(source,1),'b':(source,2)}
    cpu=cm.calculate(expressions,inputs,tmp_path/'cpu.tif',block_size=32)
    gpu=cm.calculate(expressions,inputs,tmp_path/'gpu.tif',block_size=32,device='cuda')
    with rasterio.open(cpu) as a,rasterio.open(gpu) as b:
        np.testing.assert_allclose(a.read(),b.read(),rtol=2e-5,atol=1e-5,equal_nan=True)
        assert b.tags()['device']=='cuda'


def test_cli_execution_options(cluster,write_raster,tmp_path,capsys):
    from cartomize.cli import main
    source=write_raster('input.tif',np.ones((40,40),dtype='float32'))
    assert main(['calculate','a+4',str(tmp_path/'cli.tif'),'--input','a',str(source),'1','--execution','distributed','--scheduler-address',cluster[0],'--block-size','32'])==0
    with rasterio.open(tmp_path/'cli.tif') as src:assert (src.read(1)==5).all()
