import threading

import pytest

from atlas_forge.api.plan_registry import (
    _reset_registry_for_tests,
    get_plan,
    get_plan_lock,
    register_plan,
)
from atlas_forge.models import JobPlan


@pytest.fixture(autouse=True)
def _clean_registry():
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


def test_register_plan_returns_a_stable_id_that_resolves_back_to_the_same_plan() -> None:
    plan = JobPlan(goal="AF999-US01")

    plan_id = register_plan(plan)

    assert get_plan(plan_id) is plan


def test_get_plan_returns_none_for_unknown_id() -> None:
    assert get_plan("does-not-exist") is None


def test_two_registered_plans_get_distinct_ids() -> None:
    plan_a = JobPlan(goal="AF999-US01")
    plan_b = JobPlan(goal="AF999-US02")

    id_a = register_plan(plan_a)
    id_b = register_plan(plan_b)

    assert id_a != id_b
    assert get_plan(id_a) is plan_a
    assert get_plan(id_b) is plan_b


def test_get_plan_lock_returns_the_same_lock_object_for_the_same_plan_id() -> None:
    # T-AF016-US01-08: la exclusión mutua real depende de que dos hilos
    # que piden el lock del MISMO plan_id obtengan el mismo objeto Lock
    # — si cada llamada devolviera uno nuevo, no habría exclusión alguna.
    lock_first_call = get_plan_lock("plan-1")
    lock_second_call = get_plan_lock("plan-1")

    assert lock_first_call is lock_second_call


def test_get_plan_lock_returns_different_locks_for_different_plan_ids() -> None:
    lock_a = get_plan_lock("plan-a")
    lock_b = get_plan_lock("plan-b")

    assert lock_a is not lock_b


def test_get_plan_lock_creation_is_thread_safe_under_concurrent_first_access() -> None:
    # Verifica que la creación perezosa del lock no tiene, a su vez, su
    # propia condición de carrera: muchos hilos pidiendo el lock del
    # MISMO plan_id por primera vez, casi a la vez, deben terminar todos
    # con el mismo objeto Lock — nunca crear dos Locks distintos para el
    # mismo plan_id.
    plan_id = "plan-concurrent"
    results: list[threading.Lock] = [None] * 20
    barrier = threading.Barrier(20, timeout=5.0)

    def _get_lock(index: int) -> None:
        barrier.wait()
        results[index] = get_plan_lock(plan_id)

    threads = [threading.Thread(target=_get_lock, args=(i,)) for i in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5.0)

    assert all(lock is results[0] for lock in results)
