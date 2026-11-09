// Load test: browse + search + product pages (anonymous). Run: k6 run -e BASE=https://shop.example.com k6_shop_load.js
// Do NOT point this at production checkout. Use a staging copy.
import http from 'k6/http';
import { check, sleep } from 'k6';
const BASE = __ENV.BASE || 'http://localhost:8000';
export const options = {
  stages: [{ duration: '30s', target: 20 }, { duration: '1m', target: 50 }, { duration: '30s', target: 0 }],
  thresholds: { http_req_failed: ['rate<0.01'], http_req_duration: ['p(95)<800'] },
};
export default function () {
  const pages = ['/', '/shop', '/bestsellers', '/shop?q=millet', '/robots.txt', '/sitemap.xml'];
  const r = http.get(BASE + pages[Math.floor(Math.random() * pages.length)]);
  check(r, { 'status 200': (x) => x.status === 200 });
  sleep(1);
}
