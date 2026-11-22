from __future__ import annotations

import inspect

from nickel.core import persona


def test_prompt_anchors_relative_times_on_now():
    """No PC, o Gemma somou 15 min a um horário do histórico em vez da hora atual."""
    assert '"Daqui a N minutos/horas" soma N à hora de "Agora"' in inspect.getsource(persona)
