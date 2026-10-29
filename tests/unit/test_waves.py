import pytest

from shosp_migration.source.waves import ClientStatus, GroupStatus, Wave, WaveOrigin, WaveScope


@pytest.mark.parametrize(
    ("wave", "status", "origin"),
    [
        (Wave.LEGADO_INATIVOS, ClientStatus.INATIVO, WaveOrigin.LEGADO),
        (Wave.LEGADO_ATIVOS, ClientStatus.ATIVO, WaveOrigin.LEGADO),
        (Wave.MEMED_INATIVOS, ClientStatus.INATIVO, WaveOrigin.MEMED),
        (Wave.MEMED_ATIVOS, ClientStatus.ATIVO, WaveOrigin.MEMED),
    ],
)
def test_wave_params(wave: Wave, status: ClientStatus, origin: WaveOrigin) -> None:
    scope = WaveScope(wave, GroupStatus.ATIVO)

    assert scope.params() == {
        "wave_status": status.value,
        "wave_origin": origin.value,
        "group_status": "ativo",
    }


def test_vaccines_only_in_legacy_waves() -> None:
    assert WaveScope(Wave.LEGADO_ATIVOS, GroupStatus.TODOS, include_vaccines=True).reads_vaccines

    with pytest.raises(ValueError, match="ondas legadas"):
        WaveScope(Wave.MEMED_ATIVOS, GroupStatus.TODOS, include_vaccines=True)


def test_vaccines_off_by_default() -> None:
    assert not WaveScope(Wave.LEGADO_INATIVOS, GroupStatus.ATIVO).reads_vaccines
