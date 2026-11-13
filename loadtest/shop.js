// Нагрузочный тест Shop API на k6.
//
// Два типа пользователей работают одновременно:
//   browse — гости смотрят каталог: список, поиск, карточка товара (их всегда больше всего);
//   buy    — покупатели оформляют и оплачивают заказы, часть заказов отменяют.
// После нагрузки проверяется целостность данных: остаток на складе сходится с заказами.
//
// Запуск:  k6 run loadtest/shop.js                       — профиль load
//          k6 run -e PROFILE=smoke loadtest/shop.js      — 1 пользователь, проверка, что сценарий работает
//          k6 run -e PROFILE=stress loadtest/shop.js     — поиск предела
//          k6 run -e API=http://host:8000 loadtest/shop.js
import http from 'k6/http';
import { check, group, sleep } from 'k6';
import { Counter, Trend } from 'k6/metrics';

const API = __ENV.API || 'http://localhost:8000';
const PROFILE = __ENV.PROFILE || 'load';
const JSON_HEADERS = { 'Content-Type': 'application/json' };
const START_STOCK = 1_000_000;

// Профили нагрузки: [гости, покупатели] по этапам
const PROFILES = {
  smoke: { browse: [{ duration: '10s', target: 1 }], buy: [{ duration: '10s', target: 1 }] },
  load: {   // обычный пиковый час: плавный рост, плато, спад
    browse: [{ duration: '20s', target: 20 }, { duration: '40s', target: 20 }, { duration: '10s', target: 0 }],
    buy: [{ duration: '20s', target: 10 }, { duration: '40s', target: 10 }, { duration: '10s', target: 0 }],
  },
  stress: { // ищем предел: растём, пока не начнутся ошибки
    browse: [{ duration: '30s', target: 50 }, { duration: '30s', target: 100 }, { duration: '30s', target: 150 },
      { duration: '10s', target: 0 }],
    buy: [{ duration: '30s', target: 25 }, { duration: '30s', target: 50 }, { duration: '30s', target: 75 },
      { duration: '10s', target: 0 }],
  },
};
const stages = PROFILES[PROFILE];
if (!stages) throw new Error(`Неизвестный профиль ${PROFILE}: есть ${Object.keys(PROFILES).join(', ')}`);

export const options = {
  scenarios: {
    browse: { executor: 'ramping-vus', exec: 'browse', stages: stages.browse, gracefulRampDown: '5s' },
    buy: { executor: 'ramping-vus', exec: 'buy', stages: stages.buy, gracefulRampDown: '5s' },
  },
  // Пороги — критерии прохождения. Не выполнен хотя бы один — k6 завершится с ошибкой, и CI покраснеет
  thresholds: {
    http_req_failed: ['rate<0.01'],                                   // меньше 1 % ошибок
    'http_req_duration{scenario:browse}': ['p(95)<300', 'p(99)<600'], // каталог — быстро
    'http_req_duration{name:create_order}': ['p(95)<800'],           // заказ: блокировки строк, транзакция
    'http_req_duration{name:pay}': ['p(95)<1000'],                   // оплата: ещё и запрос во внешний шлюз
    checks: ['rate>0.99'],
    'checks{type:integrity}': ['rate==1'],                           // данные после нагрузки — без расхождений
  },
  summaryTrendStats: ['avg', 'med', 'p(95)', 'p(99)', 'max'],
};

const ordersCreated = new Counter('orders_created');
const ordersPaid = new Counter('orders_paid');
const ordersCancelled = new Counter('orders_cancelled');
const checkoutTime = new Trend('checkout_duration', true); // заказ + оплата целиком, как это чувствует покупатель

function login(email, password) {
  const res = http.post(`${API}/auth/login`, JSON.stringify({ email, password }), { headers: JSON_HEADERS });
  if (res.status !== 200) throw new Error(`Не удалось войти как ${email}: ${res.status} ${res.body}`);
  return { ...JSON_HEADERS, Authorization: `Bearer ${res.json('access_token')}` };
}

// ---------- Подготовка: один раз перед нагрузкой ----------

export function setup() {
  const admin = login(__ENV.ADMIN_EMAIL || 'admin@shop.kz', __ENV.ADMIN_PASSWORD || 'admin12345');

  // Отдельный товар с большим остатком: заказы не упираются в «нет в наличии»,
  // а после теста по нему сверяется склад
  const product = http.post(`${API}/products`, JSON.stringify({
    name: `Нагрузочный товар ${Date.now()}`, category: 'loadtest', price: 4_990_00, stock: START_STOCK,
  }), { headers: admin });
  if (product.status !== 201) throw new Error(`Не удалось создать товар: ${product.status} ${product.body}`);

  // Покупатели регистрируются заранее: вход — дорогая операция (хеширование пароля),
  // её нагрузка проверяется отдельно, а не смешивается с заказами
  const run = Date.now();
  const tokens = [];
  for (let i = 0; i < 20; i++) {
    const email = `load-${run}-${i}@test.kz`;
    http.post(`${API}/auth/register`, JSON.stringify({ email, password: 'load-pass-123' }), { headers: JSON_HEADERS });
    tokens.push(login(email, 'load-pass-123').Authorization);
  }
  // Свой промокод без лимита: общий WELCOME10 закончился бы после нескольких прогонов
  const promoCode = `LOAD${run}`.slice(0, 32);
  const expires = new Date(Date.now() + 24 * 3600 * 1000).toISOString();
  const promo = http.post(`${API}/promo-codes`, JSON.stringify({
    code: promoCode, percent: 10, max_uses: 1_000_000, expires_at: expires,
  }), { headers: admin });
  if (promo.status !== 201) throw new Error(`Не удалось создать промокод: ${promo.status} ${promo.body}`);

  const catalog = http.get(`${API}/products?limit=100`).json('items').map((p) => p.id);
  return { adminAuth: admin.Authorization, productId: product.json('id'), promoCode, tokens, catalog };
}

// ---------- Гость смотрит каталог ----------

const SEARCHES = ['чайник', 'наушники', 'Samsung', 'кофе', 'рюкзак', 'нет-такого-товара'];
const pick = (list) => list[Math.floor(Math.random() * list.length)];

export function browse(data) {
  group('каталог', () => {
    const list = http.get(`${API}/products?limit=20&offset=0`, { tags: { name: 'list_products' } });
    check(list, { 'каталог: 200': (r) => r.status === 200, 'каталог: есть товары': (r) => r.json('total') > 0 });

    const search = http.get(`${API}/products?q=${encodeURIComponent(pick(SEARCHES))}`, { tags: { name: 'search' } });
    check(search, { 'поиск: 200': (r) => r.status === 200 });

    const card = http.get(`${API}/products/${pick(data.catalog)}`, { tags: { name: 'get_product' } });
    check(card, { 'карточка: 200': (r) => r.status === 200 });
  });
  sleep(0.5 + Math.random()); // пауза «на подумать» — без неё это не люди, а DDoS
}

// ---------- Покупатель оформляет заказ ----------

export function buy(data) {
  const headers = { ...JSON_HEADERS, Authorization: data.tokens[__VU % data.tokens.length] };
  const started = Date.now();

  const order = http.post(`${API}/orders`, JSON.stringify({
    items: [{ product_id: data.productId, quantity: 1 + Math.floor(Math.random() * 3) }],
    promo_code: Math.random() < 0.3 ? data.promoCode : null,
  }), { headers, tags: { name: 'create_order' } });
  if (!check(order, { 'заказ: 201': (r) => r.status === 201 })) return;
  ordersCreated.add(1);
  const orderId = order.json('id');

  const paid = http.post(`${API}/orders/${orderId}/pay`, JSON.stringify({ card_token: 'tok_visa' }),
    { headers, tags: { name: 'pay' } });
  if (check(paid, { 'оплата: заказ оплачен': (r) => r.status === 200 && r.json('status') === 'paid' })) {
    ordersPaid.add(1);
    checkoutTime.add(Date.now() - started);
  }

  if (Math.random() < 0.1) { // каждый десятый передумал — отмена с возвратом денег и товара
    const cancel = http.post(`${API}/orders/${orderId}/cancel`, null, { headers, tags: { name: 'cancel' } });
    if (check(cancel, { 'отмена: 200': (r) => r.status === 200 })) ordersCancelled.add(1);
  }
  sleep(1 + Math.random());
}

// ---------- Проверка целостности после нагрузки ----------

export function teardown(data) {
  const headers = { ...JSON_HEADERS, Authorization: data.adminAuth };
  // Заказы отдаются постранично — собираем все страницы
  const orders = [];
  for (let offset = 0; ; offset += 200) {
    const page = http.get(`${API}/orders?limit=200&offset=${offset}`, { headers, tags: { name: 'integrity' } });
    if (page.status !== 200) {
      console.error(`Не удалось получить заказы для сверки: ${page.status} ${page.body}`);
      check(null, { 'склад сходится с заказами': () => false }, { type: 'integrity' });
      return;
    }
    orders.push(...page.json());
    if (page.json().length < 200) break;
  }
  let sold = 0;
  for (const order of orders) {
    if (order.status === 'cancelled') continue;
    for (const item of order.items) if (item.product_id === data.productId) sold += item.quantity;
  }
  const stock = http.get(`${API}/products/${data.productId}`, { tags: { name: 'integrity' } }).json('stock');
  console.log(`Склад: было ${START_STOCK}, продано ${sold}, осталось ${stock}`);
  check({ sold, stock }, {
    'склад сходится с заказами': (r) => r.stock === START_STOCK - r.sold,
  }, { type: 'integrity' });
}

// ---------- Отчёт: в консоль и таблицей Markdown (в CI она попадает на страницу запуска) ----------

const ROWS = [
  ['Каталог (гости)', 'http_req_duration{scenario:browse}'],
  ['Создание заказа', 'http_req_duration{name:create_order}'],
  ['Оплата', 'http_req_duration{name:pay}'],
  ['Заказ + оплата целиком', 'checkout_duration'],
];
const ms = (v) => (v === undefined ? '—' : `${Math.round(v)} мс`);

export function handleSummary(data) {
  const m = data.metrics;
  const thresholds = Object.entries(m).flatMap(([name, metric]) =>
    Object.entries(metric.thresholds || {}).map(([rule, result]) => ({ name, rule, ok: result.ok })));
  const passed = thresholds.every((t) => t.ok);
  const value = (name, key) => m[name] && m[name].values[key];

  const md = [
    `## Нагрузочный тест — профиль \`${PROFILE}\` ${passed ? '✅' : '❌'}`,
    '',
    `Запросов: **${value('http_reqs', 'count')}** (${value('http_reqs', 'rate').toFixed(1)} в секунду), ` +
      `ошибок: **${(value('http_req_failed', 'rate') * 100).toFixed(2)} %**, ` +
      `оплачено заказов: **${value('orders_paid', 'count') || 0}**, ` +
      `пользователей одновременно: до **${value('vus_max', 'max')}**`,
    '',
    '| Операция | Медиана | 95 % | 99 % | Максимум |',
    '| --- | --- | --- | --- | --- |',
    ...ROWS.filter(([, name]) => m[name]).map(([label, name]) =>
      `| ${label} | ${ms(value(name, 'med'))} | ${ms(value(name, 'p(95)'))} | ${ms(value(name, 'p(99)'))} | ${ms(value(name, 'max'))} |`),
    '',
    '| Порог | Результат |',
    '| --- | --- |',
    ...thresholds.map((t) => `| \`${t.name}\` ${t.rule} | ${t.ok ? '✅' : '❌'} |`),
    '',
  ].join('\n');

  const text = md.replace(/\*\*|`|#+ /g, '');
  return { stdout: `\n${text}\n`, [__ENV.SUMMARY_FILE || 'loadtest-summary.md']: md };
}
