#!/bin/sh
# Запуск на бесплатном Render: тот же scripts/start.sh, плюс учебный платёжный шлюз в этом же контейнере.
# Файл оставлен, чтобы не менять команду запуска в настройках сервиса на Render.
FAKE_GATEWAY=true exec sh "$(dirname "$0")/start.sh"
