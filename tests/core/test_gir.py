import pytest

from nnsmith.abstract.dtype import DType
from nnsmith.abstract.op import *
from nnsmith.gir import *


@mark_abstract("test")
class FakeSwap(AbsOpBase):
    in_dtypes = [(i, i) for i in DTYPE_ALL]
    out_dtypes = [(i, i) for i in DTYPE_ALL]

    def __init__(self):
        super().__init__()
        self.inp_ranks = [int_all(), int_all()]

    def type_transfer(self, input_shapes: List[AbsTensor]) -> List[AbsTensor]:
        return [input_shapes[-1], input_shapes[0]]

    def deduct_inp_ranks_and_dtype(
        self, out_abs_tensor: List[AbsTensor]
    ) -> List[Tuple[int, DType]]:
        return [
            (out_abs_tensor[1].ndims, out_abs_tensor[1].dtype),
            (out_abs_tensor[0].ndims, out_abs_tensor[0].dtype),
        ]


def test_inst_expr():
    ph = Placeholder(ttype=AbsTensor(shape=[2, 3, 3], dtype=DType.float32))
    iexpr = InstExpr(ph, [])
    assert iexpr.op == ph
    assert iexpr.args == []
    assert iexpr.n_input() == 0
    assert iexpr.n_output() == 1

    op = Add()
    iexpr = InstExpr(op, ["a", "b"])
    assert iexpr.op == op
    assert iexpr.args == ["a", "b"]
    assert iexpr.n_input() == 2
    assert iexpr.n_output() == 1


def test_inst_ir():
    ph = Placeholder(ttype=AbsTensor(shape=[2, 3, 3], dtype=DType.float32))
    iexpr = InstExpr(ph, [])
    iir0 = InstIR(iexpr)
    assert iir0.iexpr == iexpr
    assert iir0.n_input() == 0
    assert iir0.n_output() == 1
    assert iir0.retval() == f"v{id(iir0)}.0"
    assert list(iir0.retvals()) == [f"v{id(iir0)}.0"]
    assert list(iir0.leaf_var()) == [f"v{id(iir0)}.0"]

    op = FakeSwap()
    iexpr = InstExpr(op, [iir0.retval(), iir0.retval()])
    iir1 = InstIR(iexpr, irctx=[iir0])
    assert iir1.iexpr == iexpr
    assert iir1.n_input() == 2
    assert iir1.n_output() == 2
    assert iir1.retval() == f"v{id(iir1)}.0"
    assert iir1.retval(0) == f"v{id(iir1)}.0"
    assert iir1.retval(1) == f"v{id(iir1)}.1"
    assert list(iir1.retvals()) == [f"v{id(iir1)}.0", f"v{id(iir1)}.1"]

    inst_id, index = InstIR.var_inst_idx(iir1.retval(1))
    assert inst_id == id(iir1)
    assert index == 1

    # Check udchain
    assert iir1.is_user_of(iir0)  # This check actually does not rely on obj id.
    assert iir1 in iir0.users[0]
    assert iir1.no_users()
    assert not iir0.is_user_of(iir1, 0)
    assert not iir0.is_user_of(iir1, 1)

    # expect exception
    with pytest.raises(ValueError):
        iir1.is_user_of(iir0, 1)  # domain \in [0, 1)


def test_gir_mutate():
    ir = GraphIR()

    ph1 = ir.add_inst(
        InstExpr(Placeholder(ttype=AbsTensor(shape=[2, 3, 3], dtype=DType.float32)), [])
    )
    # Insert
    swap1 = ir.add_inst(InstExpr(FakeSwap(), [ph1.retval(), ph1.retval()]))

    assert ir.n_var() == 3
    assert ir.n_compute_inst() == 1
    assert len(ir.leaf_inst()) == 1
    assert ir.leaf_var() == [f"v{id(swap1)}.0", f"v{id(swap1)}.1"]

    assert (
        ir.pretty()
        == """v0.0 = Placeholder() \t# inst id: 0
v1.0, v1.1 = test.FakeSwap(v0.0, v0.0) \t# inst id: 1
"""
    )

    ir.assert_wellform()

    # IR: (ph1, ph1)=>(swap)
    # Backward insert a placeholder
    ph2 = ir.add_inst(
        InstExpr(Placeholder(ttype=AbsTensor(shape=[2, 3, 3], dtype=DType.float32)), [])
    )
    # IR: (ph2, ph1)=>(swap)
    ir.replace_arg(swap1, 0, ph2.retval())

    assert ir.n_var() == 4
    assert ir.n_compute_inst() == 1
    assert len(ir.leaf_inst()) == 1
    assert ir.leaf_var() == [f"v{id(swap1)}.0", f"v{id(swap1)}.1"]
    ir.assert_wellform()

    assert (
        ir.pretty()
        == """v0.0 = Placeholder() \t# inst id: 0
v1.0 = Placeholder() \t# inst id: 1
v2.0, v2.1 = test.FakeSwap(v0.0, v1.0) \t# inst id: 2
"""
    )

    # IR: (ph2, ph1)=>(swap1)=>(swap2)
    #                       \=>swap.1
    swap2 = ir.add_inst(InstExpr(FakeSwap(), [swap1.retval(0), swap1.retval(0)]))
    assert ir.n_var() == 6
    assert ir.n_compute_inst() == 2
    assert len(ir.leaf_inst()) == 1
    assert ir.leaf_var() == [f"v{id(swap1)}.1", f"v{id(swap2)}.0", f"v{id(swap2)}.1"]
    ir.assert_wellform()

    assert (
        ir.pretty()
        == """v0.0 = Placeholder() \t# inst id: 0
v1.0 = Placeholder() \t# inst id: 1
v2.0, v2.1 = test.FakeSwap(v0.0, v1.0) \t# inst id: 2
v3.0, v3.1 = test.FakeSwap(v2.0, v2.0) \t# inst id: 3
"""
    )

    # replace swap1 with add
    # IR: (ph2, ph1)=>(add)=>(swap2)
    add = ir.add_inst(InstExpr(Add(), [ph2.retval(), ph1.retval()]))
    ir.replace_alluse(swap1.retval(0), add.retval())
    ir.remove_unused(swap1)

    assert ir.n_var() == 5
    assert ir.n_compute_inst() == 2
    assert len(ir.leaf_inst()) == 1
    assert ir.leaf_var() == [f"v{id(swap2)}.0", f"v{id(swap2)}.1"]
    ir.assert_wellform()

    assert (
        ir.pretty()
        == """v0.0 = Placeholder() \t# inst id: 0
v1.0 = Placeholder() \t# inst id: 1
v2.0 = core.Add(v0.0, v1.0) \t# inst id: 2
v3.0, v3.1 = test.FakeSwap(v2.0, v2.0) \t# inst id: 3
"""
    )


def test_gir_repair():
    # Given a graph of wrong topological order or use-def chain, we can repair it.
    ir = GraphIR()
    ph = ir.add_inst(
        InstExpr(Placeholder(ttype=AbsTensor(shape=[2, 3, 3], dtype=DType.float32)), [])
    )
    swap = ir.add_inst(InstExpr(FakeSwap(), [ph.retval(), ph.retval()]))

    ir.assert_wellform()
    assert ph.users[0] == {swap}

    # 1.1 Repair missed use.
    ph.users[0] = set()  # violate the user
    with pytest.raises(AssertionError):
        ir.assert_wellform()

    ir._udchain_repair()
    ir.assert_wellform()
    assert ph.users[0] == {swap}

    # 1.2 Repair invalid use.
    swap.users[1] = {swap}  # create non-existing use
    with pytest.raises(AssertionError):
        ir.assert_wellform()

    ir._udchain_repair()
    ir.assert_wellform()
    assert not swap.users[0]
    assert not swap.users[1]

    # 2. Repair bad topological order.
    ir.insts[0], ir.insts[1] = ir.insts[1], ir.insts[0]
    with pytest.raises(AssertionError):
        ir.assert_wellform()

    ir._topological_sort()
    ir.assert_wellform()
    assert ir.insts[0] == ph
    assert ir.insts[1] == swap