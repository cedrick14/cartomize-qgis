"""CuPy evaluation of validated raster expressions with explicit validity masks.

The same syntax and NoData rules as the CPU engine are used. Raster I/O and
calibration remain in the coordinator; only numerical arrays reach CUDA.
"""
import ast
import numpy as np
from .execution import cuda_module


def evaluate_array(expression,variables,xp,*,prepared=False):
    """Evaluate the validated AST using an array namespace (NumPy or CuPy)."""
    from .algebra import Expression
    tree=Expression(expression).tree
    def value(data,mask=False):
        data=xp.asarray(data);return data,xp.asarray(mask,dtype=bool)|~xp.isfinite(data)
    inputs=variables if prepared else {key:value(xp.asarray(np.ma.getdata(v),dtype='float64'),xp.asarray(np.ma.getmaskarray(v))) for key,v in variables.items()}
    binary={ast.Add:'add',ast.Sub:'subtract',ast.Mult:'multiply',ast.Div:'divide',ast.Pow:'power',ast.Mod:'mod',
            ast.BitAnd:'logical_and',ast.BitOr:'logical_or',ast.BitXor:'logical_xor'}
    compare={ast.Lt:'less',ast.LtE:'less_equal',ast.Gt:'greater',ast.GtE:'greater_equal',ast.Eq:'equal',ast.NotEq:'not_equal'}
    def pair(function,a,b):return value(getattr(xp,function)(a[0],b[0]),a[1]|b[1])
    def call(name,args):
        if name=='isvalid':return value(~args[0][1])
        if name=='coalesce':return value(xp.where(args[0][1],args[1][0],args[0][0]),args[0][1]&args[1][1])
        if name=='where':
            condition,a,b=args;truth=condition[0].astype(bool)
            return value(xp.where(truth,a[0],b[0]),condition[1]|xp.where(truth,a[1],b[1]))
        if name=='bitand':
            clean=[]
            for data,mask in args:
                if bool(xp.any(~mask&((data!=xp.floor(data))|(data<0)|(data>2**53-1)))):
                    raise ValueError('bitand requires nonnegative integers no larger than 2**53-1.')
                clean.append(xp.where(mask,0,data).astype('int64'))
            return value(xp.bitwise_and(*clean),args[0][1]|args[1][1])
        if name in {'mean','sum','min','max','std','median','count'}:
            data=xp.stack(xp.broadcast_arrays(*[xp.where(mask,xp.nan,raw) for raw,mask in args]))
            count=xp.sum(xp.isfinite(data),axis=0)
            if name=='count':return value(count)
            result=getattr(xp,'nan'+name)(data,axis=0)
            return value(result,count==0)
        raw=getattr(xp,name)(*[v[0] for v in args]);mask=False
        for _,m in args:mask=mask|m
        return value(raw,mask)
    def visit(node):
        if isinstance(node,ast.Constant):return value(float(node.value) if not isinstance(node.value,bool) else node.value)
        if isinstance(node,ast.Name):return value({'pi':np.pi,'e':np.e}[node.id]) if node.id in {'pi','e'} else inputs[node.id]
        if isinstance(node,ast.Call):return call(node.func.id,[visit(a) for a in node.args])
        if isinstance(node,ast.BinOp):return pair(binary[type(node.op)],visit(node.left),visit(node.right))
        if isinstance(node,ast.UnaryOp):
            data,mask=visit(node.operand)
            return value(-data if isinstance(node.op,ast.USub) else data if isinstance(node.op,ast.UAdd) else xp.logical_not(data),mask)
        if isinstance(node,ast.BoolOp):
            result=visit(node.values[0]);function='logical_and' if isinstance(node.op,ast.And) else 'logical_or'
            for child in node.values[1:]:result=pair(function,result,visit(child))
            return result
        if isinstance(node,ast.Compare):
            left=visit(node.left);result=value(True)
            for operator,right in zip(node.ops,node.comparators):
                right=visit(right);result=pair('logical_and',result,pair(compare[type(operator)],left,right));left=right
            return result
        raise ValueError('Unsupported validated syntax.')
    return visit(tree)


class CudaExpressions:
    def __init__(self,expressions):self.expressions=tuple(expressions)
    def __call__(self,variables):
        cp=cuda_module();outputs=[]
        inputs={key:(cp.asarray(np.ma.getdata(v),dtype='float64'),cp.asarray(np.ma.getmaskarray(v))) for key,v in variables.items()}
        for expression in self.expressions:
            data,mask=evaluate_array(expression,inputs,cp,prepared=True)
            outputs.append(np.ma.array(cp.asnumpy(data),mask=cp.asnumpy(mask)))
        return outputs
