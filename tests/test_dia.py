import datetime
import unittest

from badabus import dia

LINEAS = b'{"ok":true,"data":[{"id":"M03_A","lin":"M3"}]}'
DIA_LV = b'{"ok":true,"current_tipo_dia":"LV","etiqueta_dia":"Horario L - V"}'


def fake(url, timeout=10):
    if "action=lineas" in url:
        return LINEAS
    if "action=correspondencias" in url:
        return DIA_LV
    raise AssertionError("url inesperada: " + url)


class TestTipoDiaLocal(unittest.TestCase):
    def test_laborables(self):
        # 2026-07-20 es lunes; hasta el viernes 24 son laborables.
        for d in range(20, 25):
            self.assertEqual(dia.tipo_dia_local(datetime.date(2026, 7, d)), "LV")

    def test_sabado_y_domingo(self):
        self.assertEqual(dia.tipo_dia_local(datetime.date(2026, 7, 25)), "SAB")
        self.assertEqual(dia.tipo_dia_local(datetime.date(2026, 7, 26)), "DOM")


class TestTipoDiaActual(unittest.TestCase):
    def setUp(self):
        dia.limpiar_cache()

    def tearDown(self):
        dia.limpiar_cache()

    def test_consulta_el_servicio(self):
        self.assertEqual(
            dia.tipo_dia_actual(fetcher=fake, hoy=datetime.date(2026, 7, 21)),
            ("LV", "Horario L - V"),
        )

    def test_cachea_por_fecha(self):
        llamadas = []

        def contando(url, timeout=10):
            llamadas.append(url)
            return fake(url, timeout)

        hoy = datetime.date(2026, 7, 21)
        dia.tipo_dia_actual(fetcher=contando, hoy=hoy)
        n = len(llamadas)
        dia.tipo_dia_actual(fetcher=contando, hoy=hoy)
        self.assertEqual(len(llamadas), n, "el mismo día no debe volver a consultar")
        dia.tipo_dia_actual(fetcher=contando, hoy=datetime.date(2026, 7, 22))
        self.assertGreater(len(llamadas), n, "al cambiar de fecha debe consultar otra vez")

    def test_lanza_si_no_hay_lineas(self):
        def sin_lineas(url, timeout=10):
            return b'{"ok":true,"data":[]}'
        with self.assertRaises(ValueError):
            dia.tipo_dia_actual(fetcher=sin_lineas, hoy=datetime.date(2026, 7, 21))

    def test_lanza_si_no_hay_tipo_dia(self):
        def sin_tipo(url, timeout=10):
            if "action=lineas" in url:
                return LINEAS
            return b'{"ok":true}'
        with self.assertRaises(ValueError):
            dia.tipo_dia_actual(fetcher=sin_tipo, hoy=datetime.date(2026, 7, 21))


if __name__ == "__main__":
    unittest.main()
