#!/usr/bin/env bash
# Смоук-тест запущенного приложения: самый важный путь пользователя за несколько секунд.
# Запуск: ./scripts/smoke.sh [адрес API], по умолчанию http://localhost:8000
set -euo pipefail
API="${1:-http://localhost:8000}"
JSON=(-H "Content-Type: application/json")

check() {  # check <описание> <ожидаемое> <фактическое>
  if [[ "$2" == "$3" ]]; then echo "✓ $1"; else echo "✗ $1: ожидалось «$2», получено «$3»"; exit 1; fi
}

check "сервис отвечает" "ok" "$(curl -sf "$API/health" | jq -r .status)"
check "в каталоге есть товары" "true" "$(curl -sf "$API/products" | jq '.total > 0')"

EMAIL="smoke-$(date +%s)@test.kz"
curl -sf "${JSON[@]}" -d "{\"email\":\"$EMAIL\",\"password\":\"smoke-pass-1\"}" "$API/auth/register" > /dev/null
TOKEN=$(curl -sf "${JSON[@]}" -d "{\"email\":\"$EMAIL\",\"password\":\"smoke-pass-1\"}" "$API/auth/login" | jq -r .access_token)
AUTH=(-H "Authorization: Bearer $TOKEN")
check "регистрация и вход" "$EMAIL" "$(curl -sf "${AUTH[@]}" "$API/auth/me" | jq -r .email)"

ORDER=$(curl -sf "${JSON[@]}" "${AUTH[@]}" -d '{"items":[{"product_id":1,"quantity":1}],"promo_code":"WELCOME10"}' "$API/orders")
ORDER_ID=$(echo "$ORDER" | jq .id)
check "заказ с промокодом создан" "created" "$(echo "$ORDER" | jq -r .status)"
check "скидка применена" "true" "$(echo "$ORDER" | jq '.discount > 0')"

PAID=$(curl -sf "${JSON[@]}" "${AUTH[@]}" -d '{"card_token":"tok_visa"}' "$API/orders/$ORDER_ID/pay" | jq -r .status)
check "заказ оплачен через шлюз" "paid" "$PAID"

SECOND=$(curl -sf "${JSON[@]}" "${AUTH[@]}" -d '{"items":[{"product_id":2,"quantity":1}]}' "$API/orders" | jq .id)
CODE=$(curl -s -o /dev/null -w "%{http_code}" "${JSON[@]}" "${AUTH[@]}" -d '{"card_token":"tok_declined"}' \
  "$API/orders/$SECOND/pay")
check "отказ банка — ошибка 402" "402" "$CODE"
check "после отказа заказ ждёт оплаты" "created" "$(curl -sf "${AUTH[@]}" "$API/orders/$SECOND" | jq -r .status)"

echo "Смоук-тест пройден"
