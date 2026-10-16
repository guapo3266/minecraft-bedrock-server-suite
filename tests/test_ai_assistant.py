"""
tests/test_ai_assistant.py — Pruebas unitarias y de integración para el Asistente IA
=====================================================================================
Prueba la conversión de herramientas a comandos Bedrock, resolución de objetivos
automática, manejo de advertencias, parser tolerante y los endpoints de FastAPI.
"""

from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from server_gui_server import app
from gui_backend.services import ai_assistant


class TestAiAssistantUnit:
    """Pruebas unitarias de las funciones de conversión y resolución del servicio."""

    def test_format_target(self):
        assert ai_assistant.format_target("steva") == '"steva"'
        assert ai_assistant.format_target('"juan"') == '"juan"'
        assert ai_assistant.format_target("@p") == "@p"
        assert ai_assistant.format_target("@a") == "@a"
        assert ai_assistant.format_target("") == "@p"
        assert ai_assistant.format_target("  ") == "@p"

    def test_destination_coordinates_vs_player(self):
        assert ai_assistant.format_destination("100 64 -200") == "100 64 -200"
        assert ai_assistant.format_destination("~ ~10 ~") == "~ ~10 ~"
        assert ai_assistant.format_destination("juan") == '"juan"'
        assert ai_assistant.format_destination("@s") == "@s"

    def test_teleport_command(self):
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "teleport",
            {"target": "steva", "destination": "juan"}
        )
        assert cmd == 'tp "steva" "juan"'
        assert warn is None

        # Con coordenadas
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "teleport",
            {"target": "@p", "destination": "100 64 -200"}
        )
        assert cmd == "tp @p 100 64 -200"
        assert warn is None

    def test_give_item_normal_and_warnings(self):
        # Cantidad normal
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "give_item",
            {"target": "steva", "item": "diamond", "amount": 10}
        )
        assert cmd == 'give "steva" diamond 10'
        assert warn is None

        # Cantidad mayor a un stack (64)
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "give_item",
            {"target": "steva", "item": "diamond", "amount": 100}
        )
        assert cmd == 'give "steva" diamond 100'
        assert warn is not None
        assert "stack" in warn.lower()

        # Cantidad desmedida (como 73838)
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "give_item",
            {"target": "steva", "item": "diamond", "amount": 73838}
        )
        assert cmd == 'give "steva" diamond 73838'
        assert warn is not None
        assert "32,767" in warn or "32767" in warn

    def test_set_time(self):
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "set_time",
            {"time_value": "day"}
        )
        assert cmd == "time set day"
        assert warn is None

        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "set_time",
            {"time_value": "1000"}
        )
        assert cmd == "time set 1000"

    def test_set_weather(self):
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "set_weather",
            {"weather_type": "clear"}
        )
        assert cmd == "weather clear"
        assert warn is None

        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "set_weather",
            {"weather_type": "rain", "duration": 300}
        )
        assert cmd == "weather rain 300"

    def test_set_gamemode(self):
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "set_gamemode",
            {"gamemode": "creative", "target": "steva"}
        )
        assert cmd == 'gamemode creative "steva"'

        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "set_gamemode",
            {"gamemode": "survival"}
        )
        assert cmd == "gamemode survival"

    def test_apply_effect(self):
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "apply_effect",
            {"target": "steva", "effect": "speed", "seconds": 60, "amplifier": 2}
        )
        assert cmd == 'effect "steva" speed 60 2'
        assert warn is None

        # Limpiar efectos
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "apply_effect",
            {"target": "steva", "effect": "clear"}
        )
        assert cmd == 'effect "steva" clear'

    def test_manage_player(self):
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "manage_player",
            {"action": "kick", "target": "marcos", "reason": "afk"}
        )
        assert cmd == 'kick "marcos" afk'
        assert warn is not None

        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "manage_player",
            {"action": "op", "target": "steva"}
        )
        assert cmd == 'op "steva"'
        assert warn is not None

        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "manage_player",
            {"action": "kill", "target": "zombie"}
        )
        assert cmd == 'kill "zombie"'
        assert warn is not None

    def test_set_gamerule(self):
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "set_gamerule",
            {"rule": "keepinventory", "value": True}
        )
        assert cmd == "gamerule keepinventory true"

        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "set_gamerule",
            {"rule": "pvp", "value": False}
        )
        assert cmd == "gamerule pvp false"

    def test_summon_entity(self):
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "summon_entity",
            {"entity": "creeper"}
        )
        assert cmd == "summon creeper"
        assert warn is None

        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "summon_entity",
            {"entity": "wither", "target_or_coords": "~ ~1 ~"}
        )
        assert cmd == "summon wither ~ ~1 ~"
        assert warn is not None  # Wither causa advertencia

    def test_target_auto_resolution_single_player(self):
        # 1 solo jugador online: "steva"
        online = ["steva"]

        # Usuario dice "dame 64 diamantes"
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "give_item",
            {"target": "@p", "item": "diamond", "amount": 64},
            prompt="dame 64 diamantes",
            online_players=online
        )
        assert cmd == 'give "steva" diamond 64'

        # Usuario dice "teletranspórtame a juan"
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "teleport",
            {"target": "a mí", "destination": "juan"},
            prompt="teletranspórtame a juan",
            online_players=online
        )
        assert cmd == 'tp "steva" "juan"'

    def test_target_auto_resolution_multiple_or_no_players(self):
        # Múltiples jugadores: no debe auto-resolver a ninguno
        online = ["steva", "alex"]
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "give_item",
            {"target": "@p", "item": "diamond", "amount": 64},
            prompt="dame 64 diamantes",
            online_players=online
        )
        assert cmd == "give @p diamond 64"

        # 0 jugadores: mantiene @p
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "give_item",
            {"target": "@p", "item": "diamond", "amount": 64},
            prompt="dame 64 diamantes",
            online_players=[]
        )
        assert cmd == "give @p diamond 64"

    def test_parse_function_call_regex(self):
        # Formato canónico FunctionGemma
        sample1 = '<start_function_call>call:give_item{item: "diamond", amount: 64, target: "steva"}<end_function_call>'
        parsed = ai_assistant.parse_function_call(sample1)
        assert parsed is not None
        fn, args = parsed
        assert fn == "give_item"
        assert args["item"] == "diamond"
        assert args["amount"] == 64
        assert args["target"] == "steva"

        # Formato sin delimitadores exteriores
        sample2 = 'call:teleport{target: "steva", destination: "juan"}'
        parsed = ai_assistant.parse_function_call(sample2)
        assert parsed is not None
        fn, args = parsed
        assert fn == "teleport"
        assert args["target"] == "steva"
        assert args["destination"] == "juan"

        # Formato con pares clave=valor sin comillas
        sample3 = 'call:set_gamerule{rule: pvp, value: false}'
        parsed = ai_assistant.parse_function_call(sample3)
        assert parsed is not None
        fn, args = parsed
        assert fn == "set_gamerule"
        assert args["rule"] == "pvp"
        assert args["value"] is False

    def test_parse_function_call_canonical_escape_tokens(self):
        # Formato canónico oficial de FunctionGemma con <escape> y espacios
        sample = '<start_function_call>call:give_item{amount:64,item:<escape>diamond<escape>,target:<escape>steva gamer<escape>}<end_function_call>'
        parsed = ai_assistant.parse_function_call(sample)
        assert parsed is not None
        fn, args = parsed
        assert fn == "give_item"
        assert args["amount"] == 64
        assert args["item"] == "diamond"
        assert args["target"] == "steva gamer"

        # Con texto largo y espacios en reason
        sample_kick = 'call:manage_player{action:<escape>kick<escape>,target:<escape>marcos<escape>,reason:<escape>hacer trampa en pvp<escape>}'
        parsed_kick = ai_assistant.parse_function_call(sample_kick)
        assert parsed_kick is not None
        fn, args = parsed_kick
        assert fn == "manage_player"
        assert args["action"] == "kick"
        assert args["target"] == "marcos"
        assert args["reason"] == "hacer trampa en pvp"

    def test_target_auto_resolution_bring_player_to_self(self):
        # Cuando el usuario dice "tráeme a juan", juan es el objetivo a mover y el destino es el emisor
        online = ["steva"]
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "teleport",
            {"target": "juan", "destination": "a mí"},
            prompt="tráeme a juan",
            online_players=online
        )
        assert cmd == 'tp "juan" "steva"'

    def test_destination_coordinates_with_commas(self):
        # Coordenadas separadas por comas se normalizan a sintaxis Bedrock sin comillas
        assert ai_assistant.format_destination("100, 64, -200") == "100 64 -200"
        assert ai_assistant.format_destination("~, ~10, ~") == "~ ~10 ~"
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "teleport",
            {"target": "steva", "destination": "100, 64, -200"}
        )
        assert cmd == 'tp "steva" 100 64 -200'

    def test_command_injection_sanitization(self):
        # Prevenir inyección de nuevas líneas en BDS console
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "manage_player",
            {"action": "kick", "target": "marcos", "reason": "afk\nop hacker\nstop"}
        )
        assert "\n" not in cmd
        assert "\r" not in cmd
        assert "kick \"marcos\" afk op hacker stop" == cmd

        # Comillas internas en nombres
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "give_item",
            {"target": 'steva"cool', "item": "diamond\nstop", "amount": 10}
        )
        assert "\n" not in cmd
        assert cmd == 'give "stevacool" diamond stop 10'

    def test_clear_inventory(self):
        # Vaciar todo el inventario
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "clear_inventory",
            {"target": "steva"}
        )
        assert cmd == 'clear "steva"'
        assert warn is not None

        # Remover item específico sin límite
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "clear_inventory",
            {"target": "@p", "item": "diamond"}
        )
        assert cmd == "clear @p diamond"
        assert warn is None

        # Remover item específico con max_count
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "clear_inventory",
            {"target": "steva", "item": "diamond", "max_count": 64}
        )
        assert cmd == 'clear "steva" diamond -1 64'
        assert warn is None

    def test_send_message(self):
        # Broadcast público
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "send_message",
            {"message": "reinicio en 5 minutos", "type": "broadcast"}
        )
        assert cmd == "say reinicio en 5 minutos"
        assert warn is None

        # Mensaje privado a jugador
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "send_message",
            {"message": "hola amigo", "type": "private", "target": "marcos"}
        )
        assert cmd == 'msg "marcos" hola amigo'
        assert warn is None

    def test_manage_allowlist(self):
        # Agregar jugador
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "manage_allowlist",
            {"action": "add", "target": "gamer 99"}
        )
        assert cmd == 'allowlist add "gamer 99"'
        assert warn is None

        # Quitar jugador
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "manage_allowlist",
            {"action": "remove", "target": "marcos"}
        )
        assert cmd == 'allowlist remove "marcos"'

        # Acciones globales (on, off, list)
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock("manage_allowlist", {"action": "on"})
        assert cmd == "allowlist on"
        assert warn is not None

        cmd, exp, warn = ai_assistant.tool_call_to_bedrock("manage_allowlist", {"action": "off"})
        assert cmd == "allowlist off"
        assert warn is None

        cmd, exp, warn = ai_assistant.tool_call_to_bedrock("manage_allowlist", {"action": "list"})
        assert cmd == "allowlist list"
        assert warn is None

    def test_manage_experience(self):
        # Niveles positivos
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "manage_experience",
            {"target": "steva", "amount": 30, "unit": "levels"}
        )
        assert cmd == 'xp 30L "steva"'
        assert warn is None

        # Niveles negativos (permitido en Bedrock)
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "manage_experience",
            {"target": "steva", "amount": -15, "unit": "levels"}
        )
        assert cmd == 'xp -15L "steva"'
        assert warn is None

        # Puntos positivos
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "manage_experience",
            {"target": "@p", "amount": 500, "unit": "points"}
        )
        assert cmd == "xp 500 @p"
        assert warn is None

    def test_edge_cases_r3(self):
        # dale lava a steve -> give_item steve lava_bucket 1
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "give_item",
            {"target": "steve", "item": "lava_bucket", "amount": 1}
        )
        assert cmd == 'give "steve" lava_bucket 1'
        assert warn is None

        # Cantidad grande sin desbordar enteros ni romper JSON
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "give_item",
            {"target": "@p", "item": "diamond", "amount": 73838}
        )
        assert cmd == "give @p diamond 73838"
        assert warn is not None

        # Comandos administrativos con gamertags escapados entre comillas
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "manage_player",
            {"action": "kick", "target": "dark knight", "reason": "spam"}
        )
        assert cmd == 'kick "dark knight" spam'

        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "manage_player",
            {"action": "op", "target": "craft master"}
        )
        assert cmd == 'op "craft master"'

        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "manage_player",
            {"action": "deop", "target": "craft master"}
        )
        assert cmd == 'deop "craft master"'

        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "manage_player",
            {"action": "kill", "target": "'dark knight'"}
        )
        assert cmd == 'kill "dark knight"'

        # Allowlist con gamertags con espacios y comillas
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "manage_allowlist",
            {"action": "add", "target": "'xX dark Xx'"}
        )
        assert cmd == 'allowlist add "xX dark Xx"'

        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "manage_allowlist",
            {"action": "remove", "target": "xX dark Xx"}
        )
        assert cmd == 'allowlist remove "xX dark Xx"'

        # Allowlist add sin target especificado (debe tener fallback y advertencia)
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "manage_allowlist",
            {"action": "add"}
        )
        assert cmd == "allowlist add @p"
        assert warn is not None

        # Teleport con victim y destino con espacios y comillas
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "teleport",
            {"target": "'Master Chief'", "destination": "'Cool Gamer 99'"}
        )
        assert cmd == 'tp "Master Chief" "Cool Gamer 99"'

        # Selectores con comillas simples deben resolverse limpiamente
        assert ai_assistant.format_target("'@p'") == "@p"
        assert ai_assistant.format_target('"@a"') == "@a"

    def test_unrecognized_tool(self):
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "unknown_action",
            {"foo": "bar"}
        )
        assert "say Comando no reconocido" in cmd
        assert warn is not None

    def test_null_byte_injection(self):
        # 1. Sanitización de strings purga \x00
        assert ai_assistant._sanitize_string("steve\x00evil") == "steveevil"
        assert ai_assistant.format_target("steve\x00") == '"steve"'
        assert ai_assistant.format_destination("100\x00 64 -200") == "100 64 -200"

        # 2. _clean_val purga \x00 y parsea tipos
        assert ai_assistant._clean_val("30\x00") == 30
        assert ai_assistant._clean_val("true\x00") is True
        assert ai_assistant._clean_val("diamond\x00") == "diamond"

        # 3. parse_function_call con \x00 no produce JSONDecodeError y remueve \x00
        raw_call = '<start_function_call>call:give_item{target:<escape>steve\x00<escape>,item:<escape>diamond\x00<escape>,amount:64\x00}<end_function_call>'
        parsed = ai_assistant.parse_function_call(raw_call)
        assert parsed is not None
        fn, args = parsed
        assert fn == "give_item"
        assert "\x00" not in args["target"]
        assert "\x00" not in args["item"]

        # 4. tool_call_to_bedrock purga \x00 de comandos resultantes
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "give_item\x00",
            {"target": "steve\x00evil", "item": "diamond\x00evil", "amount": "64\x00"}
        )
        assert "\x00" not in cmd
        assert cmd == 'give "steveevil" diamondevil 64'

        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "manage_player",
            {"action": "kick\x00", "target": "hacker\x00", "reason": "spam\x00stop"}
        )
        assert "\x00" not in cmd
        assert cmd == 'kick "hacker" spamstop'

    def test_spanglish_and_conversational_triggers(self):
        # Auto-resolución de objetivo con modismos y Spanglish para un solo jugador online
        online = ["steva"]

        # "pásame"
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "give_item",
            {"target": "@p", "item": "diamond", "amount": 1},
            prompt="pásame un diamante porfa",
            online_players=online
        )
        assert cmd == 'give "steva" diamond 1'

        # "quiero"
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "give_item",
            {"target": "@p", "item": "apple", "amount": 64},
            prompt="quiero un stack de manzanas",
            online_players=online
        )
        assert cmd == 'give "steva" apple 64'

        # "give me" (Spanglish)
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "give_item",
            {"target": "@p", "item": "emerald", "amount": 10},
            prompt="plz give me 10 emeralds",
            online_players=online
        )
        assert cmd == 'give "steva" emerald 10'

        # "agrégame a la whitelist" con target implícito
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "manage_allowlist",
            {"action": "add"},
            prompt="agrégame a la whitelist admin",
            online_players=online
        )
        assert cmd == 'allowlist add "steva"'

    def test_multilingual_and_special_characters(self):
        # Acentos, ñ, signos de exclamación y caracteres especiales en mensajes
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "send_message",
            {"message": "¡Atención! Reinicio programado en el servidor de España & México.", "type": "broadcast"}
        )
        assert cmd == "say ¡Atención! Reinicio programado en el servidor de España & México."

        # Gamertag con guión bajo y mayúsculas mixtas
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock(
            "teleport",
            {"target": "xX_Gamer_Pro_Xx", "destination": "~ ~5 ~"}
        )
        assert cmd == 'tp "xX_Gamer_Pro_Xx" ~ ~5 ~'

    def test_r3_edge_cases_deep_verification(self):
        # 1. Gamertags numéricos no se confunden con coordenadas y son entrecomillados
        assert ai_assistant.format_destination("1234") == '"1234"'
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock("teleport", {"target": "steve", "destination": "1234"})
        assert cmd == 'tp "steve" "1234"'
        assert warn is None

        # 2. Expansiones de coordenadas relativas a 3D nativo Bedrock
        assert ai_assistant.format_destination("~") == "~ ~ ~"
        assert ai_assistant.format_destination("^") == "^ ^ ^"
        cmd, exp, warn = ai_assistant.tool_call_to_bedrock("teleport", {"target": "steve", "destination": "~"})
        assert cmd == 'tp "steve" ~ ~ ~'

        # 3. Gamerules booleanas con modismos afirmativos/negativos en español
        cmd_si, _, _ = ai_assistant.tool_call_to_bedrock("set_gamerule", {"rule": "keepinventory", "value": "sí"})
        assert cmd_si == "gamerule keepinventory true"

        cmd_on, _, _ = ai_assistant.tool_call_to_bedrock("set_gamerule", {"rule": "keepinventory", "value": "on"})
        assert cmd_on == "gamerule keepinventory true"

        cmd_act, _, _ = ai_assistant.tool_call_to_bedrock("set_gamerule", {"rule": "keepinventory", "value": "activar"})
        assert cmd_act == "gamerule keepinventory true"

        cmd_off, _, _ = ai_assistant.tool_call_to_bedrock("set_gamerule", {"rule": "keepinventory", "value": "off"})
        assert cmd_off == "gamerule keepinventory false"

        # 4. Gamerules con valores inválidos emiten advertencia explícita
        cmd_inv, _, warn_inv = ai_assistant.tool_call_to_bedrock("set_gamerule", {"rule": "keepinventory", "value": "banana"})
        assert cmd_inv == "gamerule keepinventory false"
        assert warn_inv is not None and "banana" in warn_inv

        # 5. Gamerules numéricas de Bedrock preservan números enteros
        cmd_tick, _, _ = ai_assistant.tool_call_to_bedrock("set_gamerule", {"rule": "randomTickSpeed", "value": 3})
        assert cmd_tick == "gamerule randomtickspeed 3"

        cmd_spawn, _, _ = ai_assistant.tool_call_to_bedrock("set_gamerule", {"rule": "spawnRadius", "value": 10})
        assert cmd_spawn == "gamerule spawnradius 10"

        # 6. Tolerancia a mayúsculas/minúsculas en nombres de función y claves
        cmd_case, _, _ = ai_assistant.tool_call_to_bedrock("SET_GAMEMODE", {"Gamemode": "CREATIVE", "Target": "Steve"})
        assert cmd_case == 'gamemode creative "Steve"'



class TestAiRouterEndpoints:
    """Pruebas de los endpoints /api/ai/status y /api/ai/propose con TestClient."""

    @pytest.fixture
    def client(self):
        return TestClient(app, client=("127.0.0.1", 50000), raise_server_exceptions=False)

    @patch("gui_backend.services.ai_assistant.requests.get")
    def test_ai_status_online(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"id": "functiongemma-270m-minecraft"}]
        }
        mock_get.return_value = mock_resp

        resp = client.get("/api/ai/status", headers={"Host": "127.0.0.1:8000"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["online"] is True
        assert data["model"] == "functiongemma-270m-minecraft"

    @patch("gui_backend.services.ai_assistant.requests.get")
    def test_ai_status_offline(self, mock_get, client):
        mock_get.side_effect = Exception("Connection refused")

        resp = client.get("/api/ai/status", headers={"Host": "127.0.0.1:8000"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["online"] is False
        assert data["model"] is None

    @patch("gui_backend.services.ai_assistant.requests.get")
    @patch("gui_backend.services.ai_assistant.requests.post")
    def test_ai_propose_openai_tool_calls(self, mock_post, mock_get, client):
        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.json.return_value = {"data": [{"id": "functiongemma-270m-it"}]}
        mock_get.return_value = mock_get_resp

        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "set_time",
                                    "arguments": '{"time_value": "day"}'
                                }
                            }
                        ]
                    }
                }
            ]
        }
        mock_post.return_value = mock_post_resp

        resp = client.post(
            "/api/ai/propose",
            json={"prompt": "haz de día"},
            headers={"Host": "127.0.0.1:8000"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["proposed_command"] == "time set day"
        assert data["function"] == "set_time"

    @patch("gui_backend.services.ai_assistant.requests.get")
    @patch("gui_backend.services.ai_assistant.requests.post")
    def test_ai_propose_functiongemma_raw_content(self, mock_post, mock_get, client):
        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.json.return_value = {"data": [{"id": "functiongemma"}]}
        mock_get.return_value = mock_get_resp

        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '<start_function_call>call:teleport{target: "steva", destination: "juan"}<end_function_call>'
                    }
                }
            ]
        }
        mock_post.return_value = mock_post_resp

        resp = client.post(
            "/api/ai/propose",
            json={"prompt": "teletransporta a steva a juan"},
            headers={"Host": "127.0.0.1:8000"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["proposed_command"] == 'tp "steva" "juan"'
        assert data["function"] == "teleport"

    def test_ai_propose_empty_prompt(self, client):
        resp = client.post(
            "/api/ai/propose",
            json={"prompt": "   "},
            headers={"Host": "127.0.0.1:8000"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "vacía" in data["message"]


class TestValidacion27:
    """Suite de 27 casos: 13 happy + 9 identificadores inválidos + 5 parser.
    Criterios: 0 comandos corruptos (sintaxis Bedrock válida siempre),
    0 'say Comando no reconocido' salvo el caso fuera de catálogo,
    y warning explícito ante cada identificador fuera de catálogo.
    """

    HAPPY = [
        ("teleport", {"target": "steva", "destination": "juan"}, 'tp "steva" "juan"'),
        ("give_item", {"target": "@p", "item": "diamond", "amount": 64}, "give @p diamond 64"),
        ("set_time", {"time_value": "day"}, "time set day"),
        ("set_weather", {"weather_type": "thunder"}, "weather thunder"),
        ("set_gamemode", {"gamemode": "creative", "target": "steva"}, 'gamemode creative "steva"'),
        ("apply_effect", {"target": "@p", "effect": "night_vision", "seconds": 600, "amplifier": 2}, "effect @p night_vision 600 2"),
        ("manage_player", {"action": "kick", "target": "marcos", "reason": "trampa"}, 'kick "marcos" trampa'),
        ("set_gamerule", {"rule": "pvp", "value": False}, "gamerule pvp false"),
        ("summon_entity", {"entity": "creeper", "target_or_coords": "~ ~ ~"}, "summon creeper ~ ~ ~"),
        ("clear_inventory", {"target": "juan", "item": "diamond"}, 'clear "juan" diamond'),
        ("send_message", {"message": "hola", "type": "broadcast"}, "say hola"),
        ("manage_allowlist", {"action": "add", "target": "steva"}, 'allowlist add "steva"'),
        ("manage_experience", {"target": "@p", "amount": 30, "unit": "levels"}, "xp 30L @p"),
    ]

    INVALID = [
        ("set_weather", {"weather_type": "night"}, "weather clear"),
        ("set_gamerule", {"rule": "nightvision", "value": True}, "gamerule nightvision true"),
        ("give_item", {"target": "@p", "item": "wooden_house", "amount": 1}, "give @p wooden_house 1"),
        ("summon_entity", {"entity": "dragon_xyz"}, "summon dragon_xyz"),
        ("apply_effect", {"target": "@p", "effect": "superpoder"}, "effect @p superpoder 30 0"),
        ("set_time", {"time_value": "ayer"}, "time set ayer"),
        ("set_gamemode", {"gamemode": "dios"}, "gamemode dios"),
        ("manage_player", {"action": "ban", "target": "x"}, 'ban "x"'),
        ("manage_experience", {"target": "@p", "amount": 5, "unit": "arrobas"}, "xp 5 @p"),
    ]

    def test_13_happy_exactos(self):
        assert len(self.HAPPY) == 13
        for func, args, expected in self.HAPPY:
            cmd, exp, warn = ai_assistant.tool_call_to_bedrock(func, args)
            assert cmd == expected, f"{func}: {cmd!r} != {expected!r}"
            assert " None" not in cmd and cmd.strip()
            assert "say Comando no reconocido" not in cmd

    def test_09_invalidos_avisan_y_no_corrompen(self):
        assert len(self.INVALID) == 9
        for func, args, expected in self.INVALID:
            cmd, exp, warn = ai_assistant.tool_call_to_bedrock(func, args)
            assert cmd == expected, f"{func}: {cmd!r} != {expected!r}"
            assert warn is not None and "catálogo" in warn, f"{func} sin aviso: {warn!r}"
            assert " None" not in cmd and cmd.strip()
            assert "say Comando no reconocido" not in cmd

    def test_05_parser_robusto(self):
        # 1. Duplicado con conflicto: gana la primera (valor bueno antes que el default)
        fn, args = ai_assistant.parse_function_call(
            "<start_function_call>call:give_item{amount:64,item:<escape>golden_apple<escape>,"
            "target:<escape>marcos<escape>,target:<escape>@p<escape>}<end_function_call>"
        )
        assert fn == "give_item" and args["target"] == "marcos" and args["amount"] == 64
        # 2. Enum duplicado: thunder antes que clear
        fn, args = ai_assistant.parse_function_call(
            "<start_function_call>call:set_weather{duration:None,"
            "weather_type:<escape>thunder<escape>,weather_type:<escape>clear<escape>}<end_function_call>"
        )
        assert fn == "set_weather" and args["weather_type"] == "thunder"
        cmd, _, _ = ai_assistant.tool_call_to_bedrock(fn, args)
        assert cmd == "weather thunder"
        # 3. Llamada truncada sin cierre: rescata la primera acción
        fn, args = ai_assistant.parse_function_call(
            "call:manage_allowlist{action:<escape>off<escape>,target:None,"
            "action:<escape>list<escape>,target:"
        )
        assert fn == "manage_allowlist" and args["action"] == "off"
        cmd, _, _ = ai_assistant.tool_call_to_bedrock(fn, args)
        assert cmd == "allowlist off"
        # 4. Fuera de catálogo: fallback conocido (único caso permitido con 'say Comando no reconocido')
        cmd, _, warn = ai_assistant.tool_call_to_bedrock("hacer_casa", {})
        assert "say Comando no reconocido" in cmd and warn is not None
        # 5. Mensaje vacío: avisa en vez de mandar 'say ' silencioso
        cmd, _, warn = ai_assistant.tool_call_to_bedrock(
            "send_message", {"message": "", "type": "broadcast"}
        )
        assert cmd == "say " and warn is not None


class TestSelectTools:
    """Recall del pre-filtro top-4: la tool verdadera siempre incluida."""

    def _names(self, prompt):
        return [t["function"]["name"] for t in ai_assistant.select_tools(prompt)]

    def test_recall_herramientas_principales(self):
        assert "teleport" in self._names("teletransporta a steva a juan")
        assert "teleport" in self._names("tráeme a juan")
        assert "give_item" in self._names("dame 73838 diamantes")
        assert "set_time" in self._names("haz de día")
        assert "set_weather" in self._names("pon tormenta eléctrica")
        assert "set_gamemode" in self._names("ponme en creativo")
        assert "set_gamerule" in self._names("desactiva el pvp")
        assert "apply_effect" in self._names("dame visión nocturna por 600 segundos nivel 2")
        assert "summon_entity" in self._names("spawnea un creeper aquí")
        assert "manage_player" in self._names("expulsa a marcos por hacer trampa")
        assert "clear_inventory" in self._names("vacía el inventario de juan")
        assert "send_message" in self._names("di en el chat que reinicia")
        assert "manage_allowlist" in self._names("agrega a steva a la whitelist")
        assert "manage_experience" in self._names("dame 30 niveles")

    def test_top4_por_defecto(self):
        assert len(self._names("dame diamantes")) == 4

    def test_fallback_sin_hits_no_excluye_catalogo_arbitrariamente(self):
        assert len(self._names("hola wenas")) == 13
        assert len(self._names("")) == 13
        assert len(self._names(None)) == 13
        assert self._names("hola wenas") == [t["function"]["name"] for t in ai_assistant.BEDROCK_TOOLS]
        assert len(ai_assistant.select_tools("hola wenas", top_n=2)) == 2
        assert len(ai_assistant.select_tools("hola wenas", top_n=0)) == 0
        assert len(ai_assistant.select_tools("hola wenas", top_n=None)) == 13
        assert len(ai_assistant.select_tools("hola wenas", top_n=-1)) == 0
        assert len(ai_assistant.select_tools("hola wenas", top_n="2")) == 2
        assert len(ai_assistant.select_tools(12345)) == 13
        # Con hits positivos, top_n también se respeta estrictamente
        assert len(ai_assistant.select_tools("dame diamantes", top_n=None)) == 4
        assert len(ai_assistant.select_tools("dame diamantes", top_n=2)) == 2
        assert len(ai_assistant.select_tools("dame diamantes", top_n=0)) == 0
        assert len(ai_assistant.select_tools("dame diamantes", top_n=-1)) == 0

    def test_sin_falso_positivo_di_en_diamantes(self):
        assert "send_message" not in self._names("dame 73838 diamantes")

    def test_cinco_casos_benchmark_recall(self):
        """Los 5 casos del benchmark Qwen3 que fallaban recall por colisiones léxicas."""
        assert "apply_effect" in self._names("aplica velocidad nivel 2 a juan por 120 segundos")
        assert "apply_effect" in self._names("dame resistencia por 45 segundos")
        assert "apply_effect" in self._names("aplica invisibilidad nivel 1 a lucas por 30 segundos")
        assert "apply_effect" in self._names("otorga fuerza nivel 3 a carlos durante 60 segundos")
        assert "clear_inventory" in self._names("elimina todos los diamantes de maria")

    def test_inhibicion_experiencia_cuando_hay_efecto(self):
        """'nivel' solo puntúa a manage_experience si no hay efecto presente o si va con xp/experiencia."""
        scores_efecto = ai_assistant.score_tools("aplica velocidad nivel 2 a juan por 120 segundos")
        assert scores_efecto["apply_effect"] > scores_efecto["manage_experience"]
        assert scores_efecto["manage_experience"] <= 0

        # Sin efecto, 'nivel' sí da puntos a manage_experience
        scores_xp_puro = ai_assistant.score_tools("dame 40 niveles")
        assert scores_xp_puro["manage_experience"] > 0
        assert "manage_experience" in self._names("dame 40 niveles")

        # Con 'experiencia' explícita
        scores_con_xp = ai_assistant.score_tools("dame 25 niveles de experiencia")
        assert scores_con_xp["manage_experience"] > 0
        assert "manage_experience" in self._names("dame 25 niveles de experiencia")

    def test_inhibicion_set_time_por_duracion(self):
        """'segundos' o 'ticks' no meten set_time si el contexto es efecto, clima o gamerule."""
        assert "set_time" not in self._names("aplica velocidad nivel 2 a juan por 120 segundos")[:1]
        scores_clima = ai_assistant.score_tools("pon lluvia durante 180 segundos")
        assert scores_clima["set_time"] <= 0
        assert "set_weather" in self._names("pon lluvia durante 180 segundos")

        scores_efecto = ai_assistant.score_tools("dame resistencia por 45 segundos")
        assert scores_efecto["set_time"] <= 0

        # 'ticks' en contexto horario sí puntúa a set_time
        scores_hora = ai_assistant.score_tools("establece la hora en 6000 ticks")
        assert scores_hora["set_time"] > 0
        assert "set_time" in self._names("establece la hora en 6000 ticks")

    def test_prioridad_clear_inventory_e_inhibicion_give_item(self):
        """Verbos de remoción dan prioridad a clear_inventory e inhiben give_item al retirar ítems."""
        # Retirar ítems
        names_diamantes = self._names("elimina todos los diamantes de maria")
        assert "clear_inventory" in names_diamantes
        assert "give_item" not in names_diamantes
        scores_diamantes = ai_assistant.score_tools("elimina todos los diamantes de maria")
        assert scores_diamantes["give_item"] <= 0

        names_tierra = self._names("quítame 32 bloques de tierra")
        assert "clear_inventory" in names_tierra
        assert "give_item" not in names_tierra

        names_manzanas = self._names("remueve las manzanas doradas de carlos")
        assert "clear_inventory" in names_manzanas
        assert "give_item" not in names_manzanas

        # Verbo de remoción sobre otros objetos no confunde a clear_inventory
        assert "manage_player" in self._names("elimina a carlos del mundo")
        assert "manage_allowlist" in self._names("elimina a carlos de la lista blanca")
        assert "apply_effect" in self._names("elimina los efectos que tengo activos")
        assert "set_weather" in self._names("quita la lluvia")

    def test_desambiguacion_gamerules_compuestas(self):
        """Gamerules compuestas no filtran palabras clave a otras tools."""
        assert "set_gamerule" in self._names("pon random tick speed en 3")
        assert "set_gamerule" in self._names("activa el ciclo de día y noche")
        assert "set_gamerule" in self._names("activa conservar inventario")
        assert "set_gamerule" in self._names("desactiva los daños por caída")
        assert "set_gamerule" in self._names("desactiva explosiones de TNT")

    def test_remocion_efectos_no_mete_clear_inventory(self):
        """Quitar efectos específicos puntúa a apply_effect y no a clear_inventory."""
        for prompt in ("quítame el veneno", "quítale la lentitud a juan", "elimina la debilidad"):
            scores = ai_assistant.score_tools(prompt)
            assert scores["apply_effect"] > 0
            assert scores["clear_inventory"] <= 0
            assert "apply_effect" in self._names(prompt)

    def test_pedidos_de_items_con_pocion_o_xp_no_inhiben_give_item(self):
        """Pociones o botellas de experiencia son ítems válidos y no deben inhibir give_item."""
        assert "give_item" in self._names("dame una poción")
        assert "give_item" in self._names("dame una pocion")
        assert "give_item" in self._names("dame botellas de xp")
        assert "give_item" in self._names("otorga una espada a carlos")
        scores_pocion = ai_assistant.score_tools("dame una poción")
        assert scores_pocion["give_item"] > 0

    def test_gamerules_adicionales_y_desambiguacion(self):
        """Gamerules como mobgriefing, regeneración natural y coordenadas no sangran a otras tools."""
        assert "set_gamerule" in self._names("activa mobgriefing")
        assert "set_gamerule" in self._names("activa regeneración natural")
        assert "set_gamerule" in self._names("activa las coordenadas")
        assert "set_gamerule" in self._names("elimina las explosiones de TNT")

        scores_reg = ai_assistant.score_tools("activa regeneración natural")
        assert scores_reg["set_gamerule"] > 0
        assert scores_reg["apply_effect"] <= 0

        scores_coord = ai_assistant.score_tools("activa las coordenadas")
        assert scores_coord["set_gamerule"] > 0
        assert scores_coord["teleport"] <= 0

        scores_tnt = ai_assistant.score_tools("elimina las explosiones de TNT")
        assert scores_tnt["set_gamerule"] > 0
        assert scores_tnt["clear_inventory"] <= 0

    def test_ticks_puros_y_weather_clear(self):
        """'pon 6000 ticks', 'weather clear' y 'clear inventario' dirigen a la herramienta correcta."""
        assert "set_time" in self._names("pon 6000 ticks")

        # 'clear' en clima va a set_weather, no a apply_effect
        scores_wc = ai_assistant.score_tools("weather clear")
        assert scores_wc["set_weather"] > 0
        assert scores_wc["apply_effect"] <= 0
        assert "set_weather" in self._names("weather clear")

        # 'clear' de inventario va a clear_inventory, no a apply_effect
        scores_ci = ai_assistant.score_tools("clear el inventario de juan")
        assert scores_ci["clear_inventory"] > 0
        assert scores_ci["apply_effect"] <= 0
        assert "clear_inventory" in self._names("clear el inventario de juan")

        # 'elimina la lluvia' va a set_weather, no a manage_player ni clear_inventory
        scores_rain = ai_assistant.score_tools("elimina la lluvia")
        assert scores_rain["set_weather"] > 0
        assert scores_rain["manage_player"] <= 0
        assert scores_rain["clear_inventory"] <= 0
        assert "set_weather" in self._names("elimina la lluvia")


class TestFineTuningV4Contracts:
    """Regresiones del contrato train/serving; nunca llaman a LM Studio ni BDS."""

    @pytest.mark.parametrize("prompt,expected", [
        ("deten ciclo dia y noche", "set_gamerule"),
        ("admin, evita que los incendios se extiendan", "set_gamerule"),
        ("no quiero perder mis cosas al morir", "set_gamerule"),
        ("oculta los avisos de muerte en el chat", "set_gamerule"),
        ("apaga los bloques de comandos", "set_gamerule"),
        ("registra a Neo 42 en la lista permitida", "manage_allowlist"),
        ("permite la entrada a Neo 42", "manage_allowlist"),
        ("quita el op a Neo 42", "manage_player"),
        ("bota a Neo 42 de la partida", "manage_player"),
        ("admin, suministrale un caldero a Neo 42", "give_item"),
        ("podrias darle una cubeta vacia a Neo 42", "give_item"),
        ("borra las pociones de mi inventario", "clear_inventory"),
        ("retira los efectos de pocion", "apply_effect"),
        ("elimina 10 botellas de experiencia de mi inventario", "clear_inventory"),
        ("otorgame supersalto nivel 3", "apply_effect"),
        ("dame respiracion bajo el agua", "apply_effect"),
        ("pon el mundo en tick 16000", "set_time"),
        ("trasladame a Neo 42", "teleport"),
        ("pon a Neo 42 en ~5 ~ ~-5", "teleport"),
    ])
    def test_intenciones_neutras_con_variaciones(self, prompt, expected):
        names = [t["function"]["name"] for t in ai_assistant.select_tools(prompt)]
        assert expected in names
        assert len(names) == 4

    @pytest.mark.parametrize("verb", ["di", "escribe", "susurrale", "decirle", "mandale whisper"])
    def test_mensaje_con_keywords_de_otros_comandos(self, verb):
        prompt = f"¿Podrías {verb} a Neo 42 que apaga el pvp, dame xp y elimina los efectos de lluvia?"
        scores = ai_assistant.score_tools(prompt)
        assert scores["send_message"] > 0
        assert all(score == 0 for name, score in scores.items() if name != "send_message")

    def test_normalizacion_no_muta_nombres_ni_texto(self):
        prompt = "DILE a Ñeo 42 que mañana habrá lluvia"
        with patch.object(ai_assistant, "check_lmstudio_health", return_value=(True, "qwen3-minecraft-v4")), patch.object(ai_assistant.requests, "post") as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {"choices": [{"message": {"content": "Necesito más información."}}]}
            result = ai_assistant.propose_command(prompt)
        payload = post.call_args.kwargs["json"]
        assert payload["messages"][1]["content"] == prompt
        assert payload["max_tokens"] == 512
        assert result == {"status": "error", "message": "Necesito más información."}
        assert "proposed_command" not in result

    def test_amplificador_default_y_nivel_humano(self):
        cmd, explanation, warning = ai_assistant.tool_call_to_bedrock("apply_effect", {"target": "Neo", "effect": "speed"})
        assert cmd == 'effect "Neo" speed 30 0'
        assert "nivel 1" in explanation
        assert warning is None
        cmd, explanation, _ = ai_assistant.tool_call_to_bedrock("apply_effect", {"target": "Neo", "effect": "speed", "amplifier": 2})
        assert cmd == 'effect "Neo" speed 30 2'
        assert "nivel 3" in explanation

    @pytest.mark.parametrize("human_level,model_amplifier,expected_warning", [(1, 1, True), (3, 3, True), (3, 2, False), (256, 255, False)])
    def test_guard_nivel_explicito_compatible_con_v2_v3_v4(self, human_level, model_amplifier, expected_warning):
        cmd, explanation, warning = ai_assistant.tool_call_to_bedrock(
            "apply_effect", {"target": "Neo", "effect": "speed", "amplifier": model_amplifier},
            prompt=f"Dale velocidad nivel {human_level} a Neo",
        )
        assert cmd == f'effect "Neo" speed 30 {human_level - 1}'
        assert f"nivel {human_level}" in explanation
        assert (warning is not None) == expected_warning

    @pytest.mark.parametrize("human_level", [0, 257])
    def test_nivel_fuera_de_rango_no_propone_comando(self, human_level):
        with pytest.raises(ValueError, match="nivel del efecto"):
            ai_assistant.tool_call_to_bedrock(
                "apply_effect", {"target": "Neo", "effect": "speed"},
                prompt=f"Dale velocidad nivel {human_level} a Neo",
            )

    @pytest.mark.parametrize("coords", ["Neo", "@p", "@a", "100 64"])
    def test_summon_rechaza_ubicacion_invalida(self, coords):
        with pytest.raises(ValueError, match="coordenadas X Y Z"):
            ai_assistant.tool_call_to_bedrock("summon_entity", {"entity": "cow", "target_or_coords": coords})

    def test_summon_invalido_devuelve_error_sin_comando_en_propose(self):
        with patch.object(ai_assistant, "check_lmstudio_health", return_value=(True, "qwen3-minecraft-v4")), patch.object(ai_assistant.requests, "post") as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {"choices": [{"message": {"tool_calls": [{"function": {"name": "summon_entity", "arguments": {"entity": "cow", "target_or_coords": "Neo"}}}]}}]}
            result = ai_assistant.propose_command("invoca una vaca donde esta Neo")
        assert result["status"] == "error"
        assert "coordenadas X Y Z" in result["message"]
        assert "proposed_command" not in result

    def test_truncada_no_rescata_comando_parcial(self):
        with patch.object(ai_assistant, "check_lmstudio_health", return_value=(True, "qwen3-minecraft-v4")), patch.object(ai_assistant.requests, "post") as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {"choices": [{"finish_reason": "length", "message": {"content": 'call:give_item{target:Neo,item:diamond,amount:'}}]}
            result = ai_assistant.propose_command("dale diamantes a Neo")
        assert post.call_args.kwargs["json"]["max_tokens"] == 192
        assert result["status"] == "error"
        assert "proposed_command" not in result
