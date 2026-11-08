// TV idle page. Outside text only ever goes in through textContent. A failed request keeps what is on screen.
"use strict";

const ROTATE_MS = 12000, DATA_MS = 60000, NEWS_MS = 15 * 60000, DRIFT_MS = 60000, DRIFT_PX = 6;
const WEEK_ZH = ["星期日", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六"];
const WEEK_EN = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTH_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const TOPICS = { tech: "科技 · TECH", markets: "财经 · MARKETS", discoveries: "发现 · DISCOVERIES" };

const $ = (id) => document.getElementById(id);
const set = (id, text) => { $(id).textContent = text; };
const show = (id, on) => { $(id).hidden = !on; };
const pad = (n) => String(n).padStart(2, "0");

function tick() {
  const d = new Date();
  set("clock", `${pad(d.getHours())}:${pad(d.getMinutes())}`);
  set("date-zh", `${d.getMonth() + 1}月${d.getDate()}日 ${WEEK_ZH[d.getDay()]} · 米兰`);
  set("date-en", `${WEEK_EN[d.getDay()]}, ${d.getDate()} ${MONTH_EN[d.getMonth()]} · Milan`);
}

async function getJson(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(r.status);
  return r.json();
}

function renderWeather(w) {
  show("weather", !!w);
  show("tip", !!w);
  if (!w) return;
  set("wx-icon", w.now.icon);
  set("wx-temp", `${w.now.temp}°`);
  set("wx-zh", `${w.now.zh} · 体感 ${w.now.feels}°`);
  set("wx-en", `${w.now.en} · feels ${w.now.feels}°`);
  $("wx-hours").replaceChildren(...w.hours.map((h) => {
    const cell = document.createElement("div");
    const temp = document.createElement("b");
    temp.textContent = `${h.temp}°`;
    cell.append(`${h.label}时`, temp, h.icon);
    return cell;
  }));
  set("tip-icon", w.tip.icon);
  set("tip-zh", w.tip.zh);
  set("tip-en", w.tip.en);
}

function ago(at) {
  if (at == null) return "下载中";
  const hours = Math.floor((Date.now() / 1000 - at) / 3600);
  if (hours < 1) return "刚刚";
  return hours < 24 ? `${hours} 小时前` : "昨天";
}

function renderEpisodes(list) {
  show("arrivals", list.length > 0);
  $("episodes").replaceChildren(...list.map((e) => {
    const box = document.createElement("div");
    box.className = "ep";
    const when = document.createElement("span");
    when.textContent = ago(e.at);
    const name = document.createElement("div");
    name.className = "ep-name";   // a long name is cut, the time never is
    name.textContent = e.ep ? `${e.show} · ${e.ep}` : e.show;
    box.append(name, when);
    return box;
  }));
}

function renderStatus(s) {
  show("status", !!s);
  if (s) { set("status-zh", s.zh); set("status-en", s.en); }
}

async function refresh() {
  try {
    const d = await getJson("/api/public/tv" + location.search);
    renderWeather(d.weather);
    renderEpisodes(d.episodes);
    renderStatus(d.status);
  } catch (e) { /* keep the last good data */ }
}

let stories = [], current = -1;

function paintStory() {
  const it = stories[current], next = stories[(current + 1) % stories.length];
  set("news-tag", `${TOPICS[it.topic] || it.topic.toUpperCase()} · ${it.source.toUpperCase()}`);
  set("news-title", it.title);
  set("news-summary", it.summary);
  $("news-title").lang = $("news-summary").lang = it.lang;
  set("next-title", next.title);
  $("next-title").lang = next.lang;
}

function rotate() {
  show("news", stories.length > 0);
  show("next", stories.length > 1);
  if (!stories.length) return;
  current = (current + 1) % stories.length;
  const news = $("news");
  if (news.dataset.painted) {
    news.classList.add("fading");
    setTimeout(() => { paintStory(); news.classList.remove("fading"); }, 500);
  } else {
    news.dataset.painted = "1";
    paintStory();
  }
}

async function refreshNews() {
  try {
    const d = await getJson("/api/news?topic=all");
    if (!d.items.length) return;
    const first = !stories.length;
    stories = d.items;
    current = Math.min(current, stories.length - 1);
    if (first) rotate();
  } catch (e) { /* keep the last good stories */ }
}

// Burn-in: the whole page shifts a few pixels every minute
function drift() {
  const r = () => Math.round((Math.random() * 2 - 1) * DRIFT_PX);
  $("stage").style.transform = `translate(${r()}px, ${r()}px)`;
}

tick();
refresh();
refreshNews();
setInterval(tick, 1000);
setInterval(refresh, DATA_MS);
setInterval(refreshNews, NEWS_MS);
setInterval(rotate, ROTATE_MS);
setInterval(drift, DRIFT_MS);
