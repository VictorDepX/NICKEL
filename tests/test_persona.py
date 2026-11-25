from __future__ import annotations

import inspect

from nickel.core import persona


def test_prompt_anchors_relative_times_on_now():
    """No PC, o Gemma somou 15 min a um horário do histórico em vez da hora atual."""
    assert '"Daqui a N minutos/horas" soma N à data e hora de [agora: …]' in inspect.getsource(persona)


def test_now_stamp_formats_local_time():
    from datetime import datetime, timezone as tz
    stamp = persona.now_stamp("America/Sao_Paulo", datetime(2026, 11, 25, 22, 10, tzinfo=tz.utc))
    assert stamp == "[agora: quarta, 25/11/2026 19:10]"


def test_prompt_tells_model_to_call_memory_save_directly():
    assert "chame memory_save direto" in inspect.getsource(persona)


def test_system_prompt_is_stable_across_minutes():
    """Hora no system prompt invalidava o cache do llama-server a cada minuto (~1.700 tokens relidos por turno)."""
    from datetime import datetime, timezone as tz
    a = persona.build_system_prompt(channel="ui", timezone="America/Sao_Paulo", now=datetime(2026, 11, 25, 22, 10, tzinfo=tz.utc))
    b = persona.build_system_prompt(channel="ui", timezone="America/Sao_Paulo", now=datetime(2026, 11, 26, 3, 47, tzinfo=tz.utc))
    assert a == b
    assert "Fuso do usuário: America/Sao_Paulo (UTC-03:00)" in a
