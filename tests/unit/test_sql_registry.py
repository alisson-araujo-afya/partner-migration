import pytest

from shosp_migration.source.sql_registry import (
    MissingParameterError,
    SqlRegistry,
    UnknownQueryError,
    compile_query,
    default_registry,
)

CTE = "wave as (select :wave_status as s)"

EXPECTED_QUERIES = {
    "organizations",
    "physicians",
    "patients",
    "prescription_groups",
    "prescription_items_legacy",
    "prescription_items_exam",
    "prescription_items_vaccine",
    "prescription_items_memed",
    "counts",
    "counts_vaccines",
}

WAVE_PARAMS = {
    "wave_status",
    "wave_origin",
    "group_status",
    "min_cliente",
    "max_cliente",
    "after_grupo",
}


def test_named_params_become_positional_and_reuse_numbers() -> None:
    query = compile_query("q", "select :a, :b, :a", CTE)

    assert query.text == "select $1, $2, $1"
    assert query.param_names == ("a", "b")


def test_casts_and_comments_are_preserved_or_ignored() -> None:
    query = compile_query("q", "-- usa :ignored\nselect '1'::bpchar, x = :value", CTE)

    assert query.text == "select '1'::bpchar, x = $1"
    assert query.param_names == ("value",)


def test_wave_cte_is_injected() -> None:
    query = compile_query("q", "with {{wave_cte}} select :batch", CTE)

    assert query.text == "with wave as (select $1 as s) select $2"
    assert query.param_names == ("wave_status", "batch")


def test_args_follow_param_order_and_require_all() -> None:
    query = compile_query("q", "select :b, :a", CTE)

    assert query.args({"a": 1, "b": 2, "extra": 3}) == [2, 1]
    with pytest.raises(MissingParameterError):
        query.args({"a": 1})


def test_unknown_query_is_rejected() -> None:
    registry = SqlRegistry({"_wave_cte.sql": CTE, "x.sql": "select 1"})

    assert registry.names == {"x"}
    with pytest.raises(UnknownQueryError):
        registry.get("select 1")


def test_default_registry_loads_all_versioned_queries() -> None:
    registry = default_registry()

    assert registry.names == EXPECTED_QUERIES
    for name in registry.names:
        assert "{{" not in registry.get(name).text
        assert ":" not in registry.get(name).text.replace("::", "")


@pytest.mark.parametrize(
    "name",
    ["organizations", "physicians", "patients", "prescription_groups", "counts", "counts_vaccines"],
)
def test_wave_queries_receive_wave_params(name: str) -> None:
    assert set(default_registry().get(name).param_names) >= WAVE_PARAMS


@pytest.mark.parametrize("name", ["physicians", "patients"])
def test_client_scoped_queries_fetch_the_client_without_limit(name: str) -> None:
    query = default_registry().get(name)

    assert "limit" not in query.text.lower()
    assert "batch" not in query.param_names


def test_client_status_uses_real_columns() -> None:
    text = default_registry().get("counts").text

    assert "c.ativo" not in text
    assert "c.status = '0'" in text
    assert "pe.ativo = '1'" in text
