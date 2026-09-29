"""local_sleep_date: UTC internamente, fecha fisiológica siempre en Europe/Madrid,
derivada del final del sueño — nunca truncando el UTC (Implementation Plan §6.1).
Caso obligatorio: la noche del cambio de hora, 24→25 de octubre de 2026.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from ares.timeutil import MADRID, is_dst_transition_night, local_sleep_date, to_utc


def test_noche_normal_verano_cest_utc_mas_2():
    # Duerme 23:30 CEST (25 jun) -> 07:00 CEST (26 jun); en UTC es 21:30 -> 05:00.
    sleep_end = datetime(2026, 6, 26, 5, 0, tzinfo=UTC)
    assert local_sleep_date(sleep_end) == date(2026, 6, 26)


def test_noche_que_cruza_medianoche_no_se_trunca_a_las_0h_utc():
    # 23:50 UTC del día 26 sigue siendo la noche del 26 en Madrid (CEST, +2):
    # 01:50 del 27 en local. La fecha fisiológica es el 27, no el 26.
    sleep_end = datetime(2026, 6, 26, 23, 50, tzinfo=UTC)
    assert local_sleep_date(sleep_end) == date(2026, 6, 27)


def test_cambio_de_hora_24_a_25_octubre_2026():
    # España pasa de CEST (+2) a CET (+1) a las 03:00 CEST del 25/10/2026.
    # Sueño: 23:30 CEST del 24 -> 07:15 CET del 25.
    start_local = datetime(2026, 10, 24, 23, 30, tzinfo=MADRID)
    end_local = datetime(2026, 10, 25, 7, 15, tzinfo=MADRID)
    start_utc, end_utc = to_utc(start_local), to_utc(end_local)

    assert is_dst_transition_night(start_utc, end_utc) is True
    assert local_sleep_date(end_utc) == date(2026, 10, 25)
    # La duración real (con la hora repetida) es mayor que la diferencia ingenua
    # de reloj local; comprobamos que el cálculo pasa por UTC y no se lía.
    assert (end_utc - start_utc).total_seconds() / 3600 == pytest_approx(8.75)


def pytest_approx(value: float, tol: float = 0.01) -> object:
    class _Approx:
        def __eq__(self, other: object) -> bool:
            return isinstance(other, int | float) and abs(other - value) <= tol

    return _Approx()


def test_to_utc_sin_zona_se_asume_utc():
    naive = datetime(2026, 1, 15, 10, 0)
    assert to_utc(naive) == datetime(2026, 1, 15, 10, 0, tzinfo=UTC)


def test_noche_sin_cambio_de_hora_no_se_marca():
    start = datetime(2026, 9, 20, 23, 0, tzinfo=UTC)
    end = datetime(2026, 9, 21, 4, 0, tzinfo=UTC)
    assert is_dst_transition_night(start, end) is False
