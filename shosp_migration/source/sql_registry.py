import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib import resources

_SQL_PACKAGE = "shosp_migration.source.sql"
_WAVE_CTE_FILE = "_wave_cte.sql"
_WAVE_CTE_MARKER = "{{wave_cte}}"
_LINE_COMMENT = re.compile(r"--[^\n]*")
_NAMED_PARAM = re.compile(r"(?<![:\w]):([a-z_][a-z0-9_]*)")


class UnknownQueryError(KeyError):
    pass


class MissingParameterError(ValueError):
    pass


@dataclass(frozen=True)
class Query:
    name: str
    text: str
    param_names: tuple[str, ...]

    def args(self, params: Mapping[str, object]) -> list[object]:
        missing = [name for name in self.param_names if name not in params]
        if missing:
            raise MissingParameterError(f"{self.name}: parâmetros ausentes {missing}")
        return [params[name] for name in self.param_names]


def compile_query(name: str, raw_sql: str, wave_cte: str) -> Query:
    sql = raw_sql.replace(_WAVE_CTE_MARKER, wave_cte)
    sql = _LINE_COMMENT.sub("", sql)
    param_names: list[str] = []

    def to_positional(match: re.Match[str]) -> str:
        param = match.group(1)
        if param not in param_names:
            param_names.append(param)
        return f"${param_names.index(param) + 1}"

    text = _NAMED_PARAM.sub(to_positional, sql).strip()
    return Query(name=name, text=text, param_names=tuple(param_names))


class SqlRegistry:
    def __init__(self, files: Mapping[str, str]) -> None:
        wave_cte = files[_WAVE_CTE_FILE]
        self._queries = {
            filename.removesuffix(".sql"): compile_query(
                filename.removesuffix(".sql"), content, wave_cte
            )
            for filename, content in files.items()
            if filename.endswith(".sql") and not filename.startswith("_")
        }

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._queries)

    def get(self, name: str) -> Query:
        try:
            return self._queries[name]
        except KeyError:
            raise UnknownQueryError(name) from None


@cache
def default_registry() -> SqlRegistry:
    directory = resources.files(_SQL_PACKAGE)
    files = {
        entry.name: entry.read_text(encoding="utf-8")
        for entry in directory.iterdir()
        if entry.name.endswith(".sql")
    }
    return SqlRegistry(files)
