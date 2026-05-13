import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Activity, ArrowDown, ArrowUp, ArrowUpDown, Check, CheckCircle2, ChevronDown, Clipboard, Clock3, CreditCard, Download, Home, LogOut, Pencil, Plus, RefreshCw, Server, ShoppingCart, Trash2, Upload, Users, UserCheck, UserX, X} from 'lucide-react';
import './style.css';

const api = async (path, options={}) => {
  const res = await fetch(path, { ...options, credentials:'same-origin', headers: { 'Content-Type':'application/json', ...(options.headers||{}) }});
  if (!res.ok) {
    const error = new Error(await res.text());
    error.status = res.status;
    if (res.status === 401) error.message = 'Unauthorized';
    throw error;
  }
  return res;
};

const parsePeerStats = (dump) => dump.split('\n').map(line => line.trim().split('\t')).filter(parts => parts[3]?.includes('/')).map(parts => ({
  publicKey: parts[0],
  latest: Number(parts[4] || 0),
  rx: Number(parts[5] || 0),
  tx: Number(parts[6] || 0),
}));

const formatMb = (bytes) => `${(bytes / 1024 / 1024).toFixed(bytes > 100 * 1024 * 1024 ? 0 : 1)} MB`;
const dateKey = () => new Date().toISOString().slice(0, 10);
const shiftDateKey = (key, days) => {
  const date = new Date(`${key}T00:00:00`);
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
};
const dict = {
  ru: {
    appName:'AmneziaWG Admin',
    purchase:'Покупка',
    purchaseSub:'Оформите доступ и создайте общий заказ для подключения.',
    purchaseLead:'Выберите срок, укажите логин и почту, затем отправьте заявку.',
    purchaseOrderSub:'Заказ сразу уходит в общий список активных заявок.',
    purchaseAction:'Оформить активный заказ',
    adminPanel:'Админ-панель',
    today:'Сегодня', admin:'Админ', oneDay:'1 день', threeDays:'3 дня', sevenDays:'7 дней', fifteenDays:'15 дней', oneMonth:'1 месяц', threeMonths:'3 месяца', sixMonths:'6 месяцев', oneYear:'1 год',
    online:'Онлайн', offline:'Оффлайн', recent:'Недавно', renewalPending:'Ожидает продления', checking:'Проверка сессии', signInTitle:'Вход в панель управления', login:'Логин', password:'Пароль', signIn:'Войти',
    noServer:'Сервер не выбран', noEndpoint:'endpoint не задан', refresh:'Обновить', refreshing:'Обновление', logout:'Выйти', home:'Главная', clients:'Клиенты', expired:'Просроченные', orders:'Заказы', servers:'Серверы', localServer:'Локальный сервер', allServers:'Все серверы', editName:'Редактировать имя', save:'Сохранить', cancel:'Отмена',
    totalClients:'Всего клиентов', activeClients:'Активные клиенты', expiredClients:'Просроченные клиенты', serversActive:'Серверы / активные', activeUsers:'Активные пользователи', maxOnline:'Максимум онлайн-клиентов по дням', now:'Сейчас',
    traffic:'Трафик', rx:'Прием данных', tx:'Отдача данных', peersDump:'Peers в dump', clientsSub:'Создание, выдача и скачивание конфигов для выбранного сервера',
    importConf:'Импорт .conf', createClient:'Создать клиента', importTitle:'Импорт Amnezia-конфига', close:'Закрыть', clientName:'Имя клиента', readyConf:'Готовый .conf',
    saveCopy:'Сохранить и скопировать config', server:'Сервер', term:'Срок', createIssue:'Создать и выдать config', issuedConf:'Выданный конфиг', name:'Имя', status:'Статус', limit:'Лимит',
    expires:'Окончание', publicKey:'Публичный ключ', allowedIps:'Разрешенные IP', key:'Ключ', actions:'Действия', activeClientsSub:'Клиенты с действующей подпиской и активным peer в конфиге.', expiredClientsSub:'Клиенты, которые не продлили подписку. Они заблокированы и хранятся отдельно.', blockedAt:'Заблокирован',
    deleteClient:'Удалить клиента?', copied:'Скопировано', noCopyData:'Нет данных для копирования', serverUnavailable:'Выбранный сервер недоступен. Выбери активный сервер или отредактируй подключение.',
    dataUpdated:'Данные обновлены', configCreatedCopied:'Конфиг создан и скопирован', configCreated:'Конфиг создан', configSavedCopied:'Конфиг сохранен и скопирован', configSaved:'Конфиг сохранен',
    configUnavailable:'Конфиг недоступен', configCopied:'Конфиг скопирован', staleData:'Данные уже изменил другой админ, список обновлён', clientOrOrder:'Клиент или название заказа', contact:'Контакт: Telegram, телефон, email', plan:'Тариф',
    add:'Добавить', activeOrder:'Активный', paid:'Оплачен', issued:'Выдан', closed:'Закрыт', ordersSub:'Заявки, оплаты и выдача доступов клиентам.', allOrders:'Все заказы', newOrder:'Новый заказ', recentOrders:'Последние заказы', noOrders:'Заказов пока нет', created:'Создан', serversSub:'Список подключений для управления несколькими панелями VPS',
    orderLogin:'Логин', orderEmail:'Почта', orderLoginPlaceholder:'login123', orderEmailPlaceholder:'mail@example.com',
    addServer:'Добавить сервер', editServer:'Редактировать сервер', title:'Название', panelUrl:'URL панели', token:'Токен', saveServer:'Сохранить сервер', endpoint:'URL панели', set:'Задан',
    notSet:'Не задан', active:'Активен', inactiveEdit:'Неактивен · редактировать', select:'Выбрать', edit:'Редактировать', activeServer:'Активный сервер', dumpTitle:'Активный сервер: awg dump',
    noDump:'Нет данных или awg недоступен из контейнера', wrongAuth:'Неверный логин или пароль.', details:'Подробнее', lastSeen:'Последнее подключение', never:'Никогда', download:'Скачать', copyConfig:'Скопировать конфиг', received:'Загрузка', sent:'Отдача', createdClients:'Созданных клиентов',
    loginPlaceholder:'admin', passwordPlaceholder:'admin123', clientNamePlaceholder:'iPhone Evgeny', importNamePlaceholder:'Android Evgeny', serverNamePlaceholder:'VPS NL', panelUrlPlaceholder:'http://45.15.152.113:8080', orderNamePlaceholder:'Клиент или название заказа', contactPlaceholder:'Telegram, телефон, email', currentPanel:'Текущая панель', deleteServer:'Удалить сервер?',
    sortBy:'Сортировка', sortNameAsc:'Имя A-Z', sortNameDesc:'Имя Z-A', sortCreatedDesc:'Дата создания, новые', sortCreatedAsc:'Дата создания, старые', sortLastSeenDesc:'Последнее подключение, новые', sortLastSeenAsc:'Последнее подключение, старые', selectAll:'Выбрать все', clearSelection:'Снять выбор', deleteSelected:'Удалить выбранные', selectedClients:'Выбрано клиентов', createdOnly:'Дата создания', lastConnection:'Последнее подключение', deleting:'Удаление', deleted:'Удалено', bulkActions:'Действия группы', bulkReady:'Можно удалять выбранных', purchase:'Покупка', purchaseSub:'', purchaseLead:'', purchaseOrderSub:'', purchaseAction:'', adminPanel:'Админ-панель'
  },
  us: {
    appName:'AmneziaWG Admin',
    purchase:'Purchase',
    purchaseSub:'Create a shared order for the connection.',
    purchaseLead:'Pick a term, enter login and email, then send the request.',
    purchaseOrderSub:'The order goes straight into the shared active list.',
    purchaseAction:'Place active order',
    adminPanel:'Admin panel',
    today:'Today', admin:'Admin', oneDay:'1 day', threeDays:'3 days', sevenDays:'7 days', fifteenDays:'15 days', oneMonth:'1 month', threeMonths:'3 months', sixMonths:'6 months', oneYear:'1 year',
    online:'Online', offline:'Offline', recent:'Recent', renewalPending:'Awaiting renewal', checking:'Checking session', signInTitle:'Admin panel sign in', login:'Login', password:'Password', signIn:'Sign in',
    noServer:'No server selected', noEndpoint:'endpoint not set', refresh:'Refresh', refreshing:'Refreshing', logout:'Log out', home:'Home', clients:'Clients', expired:'Expired', orders:'Orders', servers:'Servers', localServer:'Local server', allServers:'All servers', editName:'Edit name', save:'Save', cancel:'Cancel',
    totalClients:'Total clients', activeClients:'Active clients', expiredClients:'Expired clients', serversActive:'Servers / active', activeUsers:'Active users', maxOnline:'Max online clients by day', now:'Now',
    traffic:'Traffic', rx:'Received', tx:'Sent', peersDump:'Peers in dump', clientsSub:'Create, issue, and download configs for the selected server',
    importConf:'Import .conf', createClient:'Create client', importTitle:'Import Amnezia config', close:'Close', clientName:'Client name', readyConf:'Ready .conf',
    saveCopy:'Save and copy config', server:'Server', term:'Term', createIssue:'Create and issue config', issuedConf:'Issued config', name:'Name', status:'Status', limit:'Limit',
    expires:'Expires', publicKey:'Public key', allowedIps:'Allowed IPs', key:'Key', actions:'Actions', activeClientsSub:'Clients with an active subscription and peer in the config.', expiredClientsSub:'Clients who did not renew. They are blocked and stored separately.', blockedAt:'Blocked',
    deleteClient:'Delete client?', copied:'Copied', noCopyData:'No data to copy', serverUnavailable:'Selected server is unavailable. Select an active server or edit the connection.',
    dataUpdated:'Data updated', configCreatedCopied:'Config created and copied', configCreated:'Config created', configSavedCopied:'Config saved and copied', configSaved:'Config saved',
    configUnavailable:'Config unavailable', configCopied:'Config copied', staleData:'Another admin already changed this data, list refreshed', clientOrOrder:'Client or order name', contact:'Contact: Telegram, phone, email', plan:'Plan',
    add:'Add', activeOrder:'Active', paid:'Paid', issued:'Issued', closed:'Closed', ordersSub:'Requests, payments, and issuing client access.', allOrders:'All orders', newOrder:'New order', recentOrders:'Recent orders', noOrders:'No orders yet', created:'Created', serversSub:'Connection list for managing multiple VPS panels',
    orderLogin:'Login', orderEmail:'Email', orderLoginPlaceholder:'login123', orderEmailPlaceholder:'mail@example.com',
    addServer:'Add server', editServer:'Edit server', title:'Title', panelUrl:'Panel URL', token:'Token', saveServer:'Save server', endpoint:'Panel URL', set:'Set',
    notSet:'Not set', active:'Active', inactiveEdit:'Inactive · edit', select:'Select', edit:'Edit', activeServer:'Active server', dumpTitle:'Active server: awg dump',
    noDump:'No data or awg is unavailable from the container', wrongAuth:'Wrong login or password.', details:'Details', lastSeen:'Last connected', never:'Never', download:'Download', copyConfig:'Copy config', received:'Received', sent:'Sent', createdClients:'Created clients',
    loginPlaceholder:'admin', passwordPlaceholder:'admin123', clientNamePlaceholder:'iPhone Evgeny', importNamePlaceholder:'Android Evgeny', serverNamePlaceholder:'VPS NL', panelUrlPlaceholder:'http://45.15.152.113:8080', orderNamePlaceholder:'Client or order name', contactPlaceholder:'Telegram, phone, email', currentPanel:'Current panel', deleteServer:'Delete server?',
    sortBy:'Sort', sortNameAsc:'Name A-Z', sortNameDesc:'Name Z-A', sortCreatedDesc:'Created newest', sortCreatedAsc:'Created oldest', sortLastSeenDesc:'Last connected newest', sortLastSeenAsc:'Last connected oldest', selectAll:'Select all', clearSelection:'Clear selection', deleteSelected:'Delete selected', selectedClients:'Selected clients', createdOnly:'Created date', lastConnection:'Last connected', deleting:'Deleting', deleted:'Deleted', bulkActions:'Group actions', bulkReady:'Ready to delete selected', purchase:'Purchase', purchaseSub:'', purchaseLead:'', purchaseOrderSub:'', purchaseAction:'', adminPanel:'Admin panel'
  }
};

const dateLabel = (key, lang='ru') => {
  const today = dateKey();
  if (key === today) return dict[lang].today;
  return new Date(`${key}T00:00:00`).toLocaleDateString(lang === 'ru' ? 'ru-RU' : 'en-US', {day:'2-digit', month:'2-digit'});
};
const formatDate = (key, lang='ru') => key ? new Date(`${key}T00:00:00`).toLocaleDateString(lang === 'ru' ? 'ru-RU' : 'en-US', {day:'2-digit', month:'2-digit', year:'numeric'}) : '—';
const formatAnyDate = (value, lang='ru') => {
  if (!value) return '—';
  const normalized = String(value).includes('T') ? String(value) : `${value}T00:00:00`;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString(lang === 'ru' ? 'ru-RU' : 'en-US', {day:'2-digit', month:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit'});
};
const formatDateTime = (seconds, lang='ru') => {
  if (!seconds) return '—';
  const date = new Date(seconds * 1000);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString(lang === 'ru' ? 'ru-RU' : 'en-US', {day:'2-digit', month:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit'});
};
const isExpired = (key) => key ? key < dateKey() : false;
const clientTerms = [
  ['admin','admin'], ['1d','oneDay'], ['3d','threeDays'], ['7d','sevenDays'], ['15d','fifteenDays'], ['1m','oneMonth'], ['3m','threeMonths'], ['6m','sixMonths'], ['1y','oneYear'],
];
const orderStatuses = [
  ['active', 'activeOrder', Clock3],
  ['paid', 'paid', CreditCard],
  ['issued', 'issued', UserCheck],
  ['closed', 'closed', CheckCircle2],
];
const orderStatusAliases = {
  new: 'active',
  'Активный': 'active',
  'Новый': 'active',
  'Оплачен': 'paid',
  'Выдан': 'issued',
  'Закрыт': 'closed',
  Active: 'active',
  New: 'active',
  Paid: 'paid',
  Issued: 'issued',
  Closed: 'closed',
};
const normalizeOrderStatus = (status) => orderStatusAliases[status] || status || 'active';
const orderStatusClass = (status) => ({
  active: 'ok',
  new: 'ok',
  paid: 'warn',
  issued: 'ok',
  closed: 'admin',
})[normalizeOrderStatus(status)] || 'muted';

const smoothPath = (coords) => {
  if (coords.length < 2) return coords[0] ? `M ${coords[0].x} ${coords[0].y}` : '';
  return coords.reduce((path, point, index, points) => {
    if (index === 0) return `M ${point.x} ${point.y}`;
    const previous = points[index - 1];
    const controlX = (previous.x + point.x) / 2;
    return `${path} C ${controlX} ${previous.y}, ${controlX} ${point.y}, ${point.x} ${point.y}`;
  }, '');
};

function ActivityChart({points, lang}) {
  const today = dateKey();
  const data = chartDays(points);
  const values = data.map(p=>p.value);
  const max = Math.max(1, ...values);
  const width = 640;
  const height = 190;
  const step = width / Math.max(1, values.length - 1);
  const coords = values.map((value,index)=>({x:index * step, y:height - (value / max) * 150 - 20}));
  const visibleCoords = coords.filter((_,index)=>data[index].date <= today);
  const lastVisible = visibleCoords[visibleCoords.length - 1] || coords[0] || {x:0};
  const linePath = smoothPath(visibleCoords);
  const areaPath = `${linePath} L ${lastVisible.x} 170 L 0 170 Z`;
  return <svg className="chart" viewBox={`0 0 ${width} ${height}`} role="img">
    <defs><linearGradient id="chartFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#6377ff" stopOpacity=".55"/><stop offset="100%" stopColor="#6377ff" stopOpacity="0"/></linearGradient></defs>
    <polyline className="chart-grid" points={`0,170 ${width},170`} />
    <path className="chart-area" d={areaPath} fill="url(#chartFill)" />
    <path className="chart-line" d={linePath} />
    {coords.map((point,index)=><g key={data[index].date} className="chart-point">
      {data[index].date <= today && <circle className={data[index].date===today?'chart-dot today':'chart-dot'} cx={point.x} cy={point.y} r="4" />}
      {data[index].date <= today && <title>{dateLabel(data[index].date, lang)}: {data[index].value} {dict[lang].online.toLowerCase()}</title>}
    </g>)}
  </svg>;
}

function chartDays(points) {
  const today = dateKey();
  const byDate = Object.fromEntries(points.map(point=>[point.date, point.value]));
  return Array.from({length:10}, (_,index)=>shiftDateKey(today, index - 5)).map(date=>({date, value:byDate[date] || 0}));
}

function App(){
  const [pathname,setPathname]=useState(()=>window.location.pathname || '/');
  const isAdminRoute = pathname.startsWith('/admin');
  const navigate=(to)=>{
    if ((window.location.pathname || '/') === to) return;
    window.history.pushState({}, '', to);
    setPathname(to);
    window.scrollTo(0, 0);
  };
  const [view,setView]=useState('home');
  const [lang,setLang]=useState(()=>{
    const stored = localStorage.getItem('lang') || 'ru';
    return stored === 'en' ? 'us' : stored;
  });
  const uiLang = lang === 'en' ? 'us' : lang;
  const t=(key)=>dict[uiLang]?.[key] || dict.us[key] || dict.ru[key] || key;
  const setLanguage=(value)=>{ setLang(value === 'en' ? 'us' : value); localStorage.setItem('lang', value === 'en' ? 'us' : value); };
  const [username,setUsername]=useState('admin');
  const [password,setPassword]=useState('');
  const [isLoggedIn,setIsLoggedIn]=useState(false);
  const [checkingSession,setCheckingSession]=useState(true);
  const [isLoading,setIsLoading]=useState(false);
  const [isRefreshing,setIsRefreshing]=useState(false);
  const [notice,setNotice]=useState('');
  const [refreshSeq,setRefreshSeq]=useState(0);
  const [clients,setClients]=useState([]);
  const [dump,setDump]=useState('');
  const [allServerClients,setAllServerClients]=useState([]);
  const [allServerDump,setAllServerDump]=useState('');
  const [name,setName]=useState('');
  const [clientTerm,setClientTerm]=useState('admin');
  const [showClientForm,setShowClientForm]=useState(false);
  const [importName,setImportName]=useState('');
  const [importConfig,setImportConfig]=useState('');
  const [showImportForm,setShowImportForm]=useState(false);
  const [clientServerId,setClientServerId]=useState(()=>localStorage.getItem('activeServerId')||'local');
  const [clientConfigs,setClientConfigs]=useState(()=>JSON.parse(localStorage.getItem('clientConfigs')||'{}'));
  const [selectedConfig,setSelectedConfig]=useState('');
  const [showServerForm,setShowServerForm]=useState(false);
  const [serverName,setServerName]=useState('');
  const [serverBaseUrl,setServerBaseUrl]=useState('');
  const [serverToken,setServerToken]=useState('');
  const [serverMaxUsers,setServerMaxUsers]=useState('');
  const [editingServerId,setEditingServerId]=useState(null);
  const [serverLimitDrafts,setServerLimitDrafts]=useState({});
  const [activeServerId,setActiveServerId]=useState(()=>localStorage.getItem('activeServerId')||'local');
  const [servers,setServers]=useState([]);
  const [orderLogin,setOrderLogin]=useState('');
  const [orderEmail,setOrderEmail]=useState('');
  const [orderPlan,setOrderPlan]=useState('1 месяц');
  const [orders,setOrders]=useState([]);
  const [activityHistory,setActivityHistory]=useState(()=>JSON.parse(localStorage.getItem('dailyActivityHistory')||'[]'));
  const [lastConfig,setLastConfig]=useState('');
  const [error,setError]=useState('');
  const [editingClientKey,setEditingClientKey]=useState('');
  const [editingClientName,setEditingClientName]=useState('');
  const [expandedClientKey,setExpandedClientKey]=useState('');
  const [expandedServerId,setExpandedServerId]=useState('');
  const [selectedClientKeys,setSelectedClientKeys]=useState(()=>new Set());
  const [bulkDeleteState,setBulkDeleteState]=useState({running:false,total:0,done:0,last:''});
  const [clientSortField,setClientSortField]=useState('name');
  const [clientSortDir,setClientSortDir]=useState('asc');
  const selectionDragRef = useRef({active:false, desired:false, suppressClick:false, lastKey:''});
  const isAggregateServer = activeServerId === 'all';

  useEffect(()=>{
    const onPopState = ()=>setPathname(window.location.pathname || '/');
    window.addEventListener('popstate', onPopState);
    return ()=>window.removeEventListener('popstate', onPopState);
  },[]);

  useEffect(()=>{
    document.title = isAdminRoute ? t('appName') : `${t('appName')} · ${t('purchase')}`;
  },[isAdminRoute, lang]);

  const handleError=(e)=>{
    const message = e.message === 'Unauthorized' ? t('wrongAuth') : e.message;
    setError(message);
    if (e.message === 'Unauthorized') {
      setIsLoggedIn(false);
      setClients([]);
      setDump('');
      setAllServerClients([]);
      setAllServerDump('');
    }
  };

  const loadServers=async()=>{
    const r=await api('/api/servers');
    const j=await r.json();
    const next = j.servers || [];
    setServers(next);
    setServerLimitDrafts(current => {
      const nextDrafts = { ...current };
      next.forEach(server => {
        if (nextDrafts[server.id] === undefined) {
          nextDrafts[server.id] = server.maxUsers ? String(server.maxUsers) : '';
        }
      });
      Object.keys(nextDrafts).forEach(id => {
        if (!next.some(server => server.id === id)) delete nextDrafts[id];
      });
      return nextDrafts;
    });
    if (activeServerId === 'all') return 'all';
    if (!next.some(server=>server.id===activeServerId)) {
      const first = next[0]?.id || 'local';
      setActiveServerId(first);
      setClientServerId(first);
      localStorage.setItem('activeServerId', first);
      return first;
    }
    return activeServerId;
  };

  const loadClients=async(serverId=activeServerId,{manual=false}={})=>{
    if (manual) setIsRefreshing(true);
    setError('');
    try {
      const query = serverId ? `?server_id=${encodeURIComponent(serverId)}` : '';
      const r=await api(`/api/clients${query}`);
      const j=await r.json();
      setClients(j.clients||[]); setDump(j.dump||'');
      setRefreshSeq(seq=>seq + 1);
      setIsLoggedIn(true);
      if (manual) {
        setNotice(t('dataUpdated'));
        setTimeout(()=>setNotice(''), 2500);
      }
    } finally {
      if (manual) setIsRefreshing(false);
    }
  };
  const loadAllServerStats=async()=>{
    const r=await api('/api/clients?server_id=all');
    const j=await r.json();
    setAllServerClients(j.clients||[]);
    setAllServerDump(j.dump||'');
  };

  const load=async({manual=false}={})=>{
    const serverId = await loadServers().catch(handleError);
    if (serverId) setIsLoggedIn(true);
    if (serverId) {
      await loadClients(serverId, {manual}).catch(handleError);
      await loadAllServerStats().catch(()=>{});
    }
    if (isAdminRoute) {
      await loadOrders().catch(handleError);
    }
  };

  const login=async()=>{
    setError('');
    await api('/api/login',{method:'POST',body:JSON.stringify({username:username.trim(),password})});
    setIsLoggedIn(true);
    setPassword('');
    await load();
  };

  const saveClientConfig=(publicKey, config)=>{
    const next = {...clientConfigs, [publicKey]: config};
    setClientConfigs(next);
    localStorage.setItem('clientConfigs', JSON.stringify(next));
  };
  const fetchClientConfig=async(publicKey, serverId=activeServerId)=>{
    const query = serverId ? `&server_id=${encodeURIComponent(serverId)}` : '';
    const r=await api(`/api/client-config?public_key=${encodeURIComponent(publicKey)}${query}`);
    return await r.text();
  };
  const copyText=async(text, success='Скопировано')=>{
    const value = String(text || '');
    if (!value) throw new Error(t('noCopyData'));
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
    } else {
      const ta = document.createElement('textarea');
      ta.value = value;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    }
    setNotice(success);
    setTimeout(()=>setNotice(''), 2000);
  };
  const create=async()=>{
    const targetServer = servers.find(s=>s.id===clientServerId);
    if(!targetServer || !serverConnection(targetServer)){
      setError(t('serverUnavailable'));
      return;
    }
    const query = clientServerId ? `?server_id=${encodeURIComponent(clientServerId)}` : '';
    const r=await api(`/api/clients${query}`,{method:'POST',body:JSON.stringify({name, term:clientTerm})});
    const j=await r.json();
    setLastConfig(j.config);
    saveClientConfig(j.publicKey, j.config);
    setName('');
    setClientTerm('admin');
    setShowClientForm(false);
    await load();
    setSelectedConfig(j.config);
    await copyText(j.config, t('configCreatedCopied')).catch(()=>setNotice(t('configCreated')));
  };
  const importClient=async()=>{
    const query = clientServerId ? `?server_id=${encodeURIComponent(clientServerId)}` : '';
    const r=await api(`/api/client-import${query}`,{method:'POST',body:JSON.stringify({name:importName,config:importConfig})});
    const j=await r.json();
    saveClientConfig(j.publicKey, j.config);
    setImportName('');
    setImportConfig('');
    setShowImportForm(false);
    await load();
    setSelectedConfig(j.config);
    await copyText(j.config, t('configSavedCopied')).catch(()=>setNotice(t('configSaved')));
  };

  const deleteClientEntry=async(pk, serverId=activeServerId)=>{
    const savedConfig = clientConfigs[pk];
    const params = new URLSearchParams({public_key: pk});
    if (serverId) params.set('server_id', serverId);
    try {
      await api(`/api/clients?${params.toString()}`,{method:'DELETE'});
    } catch (error) {
      if (error.status === 404) {
        await load().catch(handleError);
        setNotice(t('staleData'));
        setTimeout(()=>setNotice(''), 2500);
        return;
      }
      throw error;
    }
    if (savedConfig) {
      const next = {...clientConfigs};
      delete next[pk];
      setClientConfigs(next);
      localStorage.setItem('clientConfigs', JSON.stringify(next));
      if (selectedConfig === savedConfig || lastConfig === savedConfig) {
        closeIssuedConfig();
      }
    }
  };
  const remove=async(pk, serverId=activeServerId, {confirmDelete=true}={})=>{
    if(confirmDelete && !confirm(t('deleteClient'))) return;
    await deleteClientEntry(pk, serverId);
    await load();
  };
  const clientRowKey=(client)=>`${client.serverId || 'local'}:${client.PublicKey}`;
  const beginEditClient=(client)=>{
    setEditingClientKey(clientRowKey(client));
    setEditingClientName(client.name || '');
  };
  const cancelEditClient=()=>{
    setEditingClientKey('');
    setEditingClientName('');
  };
  const renameClient=async(client)=>{
    const nextName = editingClientName.trim();
    if(!nextName) return;
    const serverId = client.serverId || activeServerId;
    const params = new URLSearchParams({public_key: client.PublicKey});
    if (serverId) params.set('server_id', serverId);
    try {
      await api(`/api/clients?${params.toString()}`,{method:'PATCH',body:JSON.stringify({name:nextName})});
    } catch (error) {
      if (error.status === 404) {
        cancelEditClient();
        await load().catch(handleError);
        setNotice(t('staleData'));
        setTimeout(()=>setNotice(''), 2500);
        return;
      }
      throw error;
    }
    cancelEditClient();
    await load();
  };
  const downloadConfig=(config, filename='amneziawg-client.conf')=>{ const a=document.createElement('a'); a.href=URL.createObjectURL(new Blob([config],{type:'text/plain'})); a.download=filename; a.click(); };
  const download=()=>downloadConfig(lastConfig);
  const downloadClientConfig=async(publicKey, fallbackName='client', serverId=activeServerId)=>{
    const config = await fetchClientConfig(publicKey, serverId).catch(()=>clientConfigs[publicKey]);
    if (!config) throw new Error(t('configUnavailable'));
    downloadConfig(config, `${fallbackName || publicKey || 'client'}.conf`);
  };
  const copyClientConfig=async(publicKey, serverId=activeServerId)=>{
    const config = await fetchClientConfig(publicKey, serverId).catch(()=>clientConfigs[publicKey]);
    if (!config) throw new Error(t('configUnavailable'));
    await copyText(config, t('configCopied'));
  };
  const closeIssuedConfig=()=>{ setSelectedConfig(''); setLastConfig(''); };
  const logout=async()=>{ await api('/api/logout',{method:'POST'}).catch(()=>{}); setIsLoggedIn(false); setClients([]); setDump(''); setAllServerClients([]); setAllServerDump(''); setError(''); setNotice(''); };
  const addServer=async()=>{
    const editingLocal = editingServerId === 'local';
    if(!serverName.trim()) return;
    if(!editingLocal && (!serverBaseUrl.trim() || !serverToken.trim())) return;
    const maxUsers = serverMaxUsers.trim() === '' ? 0 : Math.max(0, Number.parseInt(serverMaxUsers, 10) || 0);
    if(editingServerId){
      const payload = editingLocal
        ? {name:serverName.trim(),maxUsers}
        : {name:serverName.trim(),baseUrl:serverBaseUrl.trim(),token:serverToken.trim(),maxUsers};
      await api('/api/servers/'+encodeURIComponent(editingServerId),{method:'PUT',body:JSON.stringify(payload)});
      const nextActive = await loadServers();
      await loadClients(nextActive || activeServerId).catch(handleError);
    } else {
      const r=await api('/api/servers',{method:'POST',body:JSON.stringify({name:serverName.trim(),baseUrl:serverBaseUrl.trim(),token:serverToken.trim(),maxUsers})});
      const j=await r.json();
      await loadServers();
      if (j.server?.id) {
        await selectServer(j.server.id);
      }
    }
    setServerName(''); setServerBaseUrl(''); setServerToken(''); setServerMaxUsers(''); setShowServerForm(false);
    setEditingServerId(null);
  };
  const selectServer=(id)=>{ setActiveServerId(id); if (id !== 'all') setClientServerId(id); localStorage.setItem('activeServerId',id); if(id) loadClients(id).catch(handleError); };
  const editServer=(server)=>{
    setEditingServerId(server.id);
    setServerName(server.name);
    setServerBaseUrl(server.baseUrl || '');
    setServerToken(server.token || '');
    setServerMaxUsers(server.maxUsers ? String(server.maxUsers) : '');
    setShowServerForm(true);
  };
  const closeServerForm=()=>{
    setShowServerForm(false);
    setEditingServerId(null);
    setServerName('');
    setServerBaseUrl('');
    setServerToken('');
    setServerMaxUsers('');
  };
  const serverLimitValue = (server) => serverLimitDrafts[server.id] ?? (server.maxUsers ? String(server.maxUsers) : '');
  const saveServerLimit = async (server, rawValue) => {
    const maxUsers = rawValue.trim() === '' ? 0 : Math.max(0, Number.parseInt(rawValue, 10) || 0);
    const currentMaxUsers = Number(server.maxUsers || 0);
    if (currentMaxUsers === maxUsers) {
      setServerLimitDrafts(current => {
        const next = { ...current };
        delete next[server.id];
        return next;
      });
      return;
    }
    const payload = {
      name: server.name || '',
      baseUrl: server.kind === 'local' ? undefined : server.baseUrl,
      token: server.kind === 'local' ? undefined : (server.token || ''),
      maxUsers,
    };
    if (server.kind === 'local') {
      delete payload.baseUrl;
      delete payload.token;
    }
    try {
      await api('/api/servers/'+encodeURIComponent(server.id),{method:'PUT',body:JSON.stringify(payload)});
    } catch (error) {
      if (error.status === 404) {
        await loadServers().catch(handleError);
        setNotice(t('staleData'));
        setTimeout(()=>setNotice(''), 2500);
        return;
      }
      throw error;
    }
    setServerLimitDrafts(current => {
      const next = { ...current };
      delete next[server.id];
      return next;
    });
    const nextActive = await loadServers();
    if (nextActive) await loadClients(nextActive).catch(handleError);
  };
  const deleteServer=(id)=>{
    if(id === 'local') return;
    api('/api/servers/'+encodeURIComponent(id),{method:'DELETE'})
      .then(async()=>{ const next = await loadServers(); if(activeServerId===id) selectServer(next[0]?.id || 'local'); })
      .catch(handleError);
  };
  const normalizeOrder = (order) => ({
    ...order,
    login: order.login || order.name || '',
    email: order.email || order.contact || '',
    term: order.term || order.plan || '',
    created: order.created || order.createdAt || '',
  });
  const loadOrders = async () => {
    if (!isAdminRoute || !isLoggedIn) return;
    const r = await api('/api/orders');
    const j = await r.json();
    setOrders((j.orders || []).map(normalizeOrder));
  };
  const saveOrders = (next) => setOrders(next.map(normalizeOrder));
  const addOrder = async () => {
    const login = orderLogin.trim();
    const email = orderEmail.trim();
    const term = orderPlan;
    if(!login || !email) return;
    const r = await api('/api/orders',{method:'POST',body:JSON.stringify({login,email,term})});
    const j = await r.json();
    const created = normalizeOrder(j.order || {});
    setOrders(current=>[created, ...current.filter(order=>order.id !== created.id)]);
    setOrderLogin('');
    setOrderEmail('');
    if (isAdminRoute) {
      await loadOrders();
    }
  };
  const updateOrder=async(id,status)=>{
    if (!isAdminRoute || !isLoggedIn) return;
    try {
      const r = await api(`/api/orders/${encodeURIComponent(id)}`,{method:'PATCH',body:JSON.stringify({status})});
      const j = await r.json();
      const updated = normalizeOrder(j.order || {});
      setOrders(current=>current.map(order=>order.id===updated.id ? updated : order));
    } catch (error) {
      if (error.status === 404) {
        await loadOrders().catch(handleError);
        setNotice(t('staleData'));
        setTimeout(()=>setNotice(''), 2500);
        return;
      }
      throw error;
    }
  };
  const deleteOrder=async(id)=>{
    if (!isAdminRoute || !isLoggedIn) return;
    try {
      await api(`/api/orders/${encodeURIComponent(id)}`,{method:'DELETE'});
      setOrders(current=>current.filter(order=>order.id!==id));
    } catch (error) {
      if (error.status === 404) {
        await loadOrders().catch(handleError);
        setNotice(t('staleData'));
        setTimeout(()=>setNotice(''), 2500);
        return;
      }
      throw error;
    }
  };

  useEffect(()=>{
    if (!isAdminRoute) {
      setCheckingSession(false);
      return;
    }
    load().catch(()=>setIsLoggedIn(false)).finally(()=>setCheckingSession(false));
  },[isAdminRoute]);

  const nav = [
    ['home',t('home'),Home],
    ['clients',t('clients'),Users],
    ['expired',t('expired'),UserX],
    ['orders',t('orders'),ShoppingCart],
    ['server',t('servers'),Server],
  ];
  const authed = isLoggedIn;
  const activeServer = isAggregateServer
    ? {id:'all', name:t('allServers'), baseUrl:'', kind:'aggregate', status:'online'}
    : servers.find(s=>s.id===activeServerId) || servers[0] || {id:'local', name:t('currentPanel'), baseUrl:'local', status:'online'};
  const serverConnection = (server)=>Boolean(server) && (server.id === 'local' || server.id === 'all' || server.status === 'online');
  const serverNameById = (serverId)=>{
    if (serverId === 'all') return t('allServers');
    if (serverId === 'local') return t('localServer');
    return servers.find(server=>server.id===serverId)?.name || serverId || '—';
  };
  const clientServerName = (client)=>client.serverName || serverNameById(client.serverId);
  const activeClientsList = clients.filter(client=>!client.blocked);
  const pendingRenewalClients = clients.filter(client=>client.blocked || ['not_renewed','renewal_pending'].includes(client.status));
  const peerStats = parsePeerStats(dump);
  const peerStatsByKey = Object.fromEntries(peerStats.map(peer=>[peer.publicKey, peer]));
  const allServerStatsClients = allServerClients.length ? allServerClients : clients;
  const allServerPeerStats = parsePeerStats(allServerDump || dump);
  const nowSeconds = Math.floor(Date.now() / 1000);
  const activeClientTotal = allServerStatsClients.filter(client=>!client.blocked).length;
  const totalServerMaxUsers = servers.reduce((sum, server) => sum + Number(server.maxUsers || 0), 0);
  const activeClientCount = peerStats.filter(peer=>peer.latest && nowSeconds - peer.latest < 60).length;
  const totalRx = peerStats.reduce((sum,peer)=>sum + peer.rx, 0);
  const totalTx = peerStats.reduce((sum,peer)=>sum + peer.tx, 0);
  const allServerActiveClientCount = allServerPeerStats.filter(peer=>peer.latest && nowSeconds - peer.latest < 60).length;
  const allServerTotalRx = allServerPeerStats.reduce((sum,peer)=>sum + peer.rx, 0);
  const allServerTotalTx = allServerPeerStats.reduce((sum,peer)=>sum + peer.tx, 0);
  const activeServerCount = servers.filter(server=>server.status === 'online').length;
  const editingLocalServer = editingServerId === 'local';
  const orderCounts = orderStatuses.reduce((counts,[status])=>({
    ...counts,
    [status]: orders.filter(order=>normalizeOrderStatus(order.status) === status).length,
  }), {});

  useEffect(()=>{
    if (!isAdminRoute || !isLoggedIn || !servers.length) return;
    if (activeServerId === 'all') return;
    if (!servers.some(server=>server.id===activeServerId)) {
      const next = servers[0].id;
      setActiveServerId(next);
      setClientServerId(next);
      localStorage.setItem('activeServerId', next);
      loadClients(next).catch(handleError);
    }
  },[isAdminRoute, isLoggedIn, servers, activeServerId]);

  useEffect(()=>{
    if(!isAdminRoute || !isLoggedIn) return;
    setActivityHistory(current=>{
      const key = dateKey();
      const existing = current.find(point=>point.date===key);
      const next = existing
        ? current.map(point=>point.date===key ? {...point, value:Math.max(point.value, activeClientCount), current:activeClientCount} : point)
        : [...current, {date:key, value:activeClientCount, current:activeClientCount}];
      const limited = next.slice(-14);
      localStorage.setItem('dailyActivityHistory',JSON.stringify(limited));
      return limited;
    });
  },[isAdminRoute, isLoggedIn, activeClientCount, refreshSeq]);

  useEffect(()=>{
    if(!isAdminRoute || !isLoggedIn) return;
    const timer = setInterval(()=>load().catch(handleError), 5000);
    return ()=>clearInterval(timer);
  },[isAdminRoute, isLoggedIn, activeServerId]);

  useEffect(()=>{
    if(!isAdminRoute || !isLoggedIn || view !== 'server') return;
    loadAllServerStats().catch(()=>{});
  },[isAdminRoute, isLoggedIn, view, servers.length]);

  useEffect(()=>{
    const stopSelectionDrag = () => {
      if (!selectionDragRef.current.active) return;
      selectionDragRef.current.active = false;
      selectionDragRef.current.lastKey = '';
      selectionDragRef.current.suppressClick = true;
      window.setTimeout(()=>{ selectionDragRef.current.suppressClick = false; }, 0);
    };
    window.addEventListener('mouseup', stopSelectionDrag);
    window.addEventListener('blur', stopSelectionDrag);
    return ()=>{
      window.removeEventListener('mouseup', stopSelectionDrag);
      window.removeEventListener('blur', stopSelectionDrag);
    };
  },[]);

  useEffect(()=>{
    if (!isAdminRoute || !isLoggedIn) return;
    const syncNow = () => load().catch(handleError);
    const onVisibility = () => {
      if (!document.hidden) syncNow();
    };
    window.addEventListener('focus', syncNow);
    document.addEventListener('visibilitychange', onVisibility);
    return ()=>{
      window.removeEventListener('focus', syncNow);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  },[isAdminRoute, isLoggedIn, activeServerId]);

  const clientStatus = (client)=>{
    const publicKey = client?.PublicKey;
    const sourceServerId = client?.serverId;
    const sourcePublicKey = client?.PublicKey;
    const matchedClient = clients.find(item=>item.PublicKey === publicKey && (!sourceServerId || item.serverId === sourceServerId));
    const resolved = matchedClient || client;
    const stat = peerStatsByKey[sourcePublicKey];
    if (resolved?.blocked) return {label:t('renewalPending'), className:'expired'};
    if(!stat?.latest) return {label:t('offline'), className:'muted'};
    const age = nowSeconds - stat.latest;
    if(age < 60) return {label:t('online'), className:'ok'};
    if(age < 900) return {label:t('recent'), className:'warn'};
    return {label:t('offline'), className:'muted'};
  };
  const clientPeerStat = (client)=>peerStatsByKey[client?.PublicKey] || null;
  const lastSeenText = (client)=>{
    const latest = clientPeerStat(client)?.latest;
    return latest ? formatDateTime(latest, lang) : t('never');
  };
  const isClientSelected = (key) => selectedClientKeys.has(key);
  const applyClientSelection = (key, selected) => {
    setSelectedClientKeys(current => {
      const next = new Set(current);
      if (selected) next.add(key);
      else next.delete(key);
      return next;
    });
  };
  const toggleClientSelected = (client) => {
    const key = clientRowKey(client);
    setSelectedClientKeys(current => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };
  const beginClientSelectionDrag = (client, event) => {
    if (!selectedClientKeys.size) return;
    if (event.button !== 0) return;
    event.preventDefault();
    const key = clientRowKey(client);
    const desired = !isClientSelected(key);
    selectionDragRef.current.active = true;
    selectionDragRef.current.desired = desired;
    selectionDragRef.current.lastKey = key;
    applyClientSelection(key, desired);
  };
  const continueClientSelectionDrag = (client) => {
    const drag = selectionDragRef.current;
    if (!drag.active) return;
    const key = clientRowKey(client);
    if (drag.lastKey === key) return;
    drag.lastKey = key;
    applyClientSelection(key, drag.desired);
  };
  const clearClientSelection = () => setSelectedClientKeys(new Set());
  const selectAllVisibleClients = () => {
    const list = view === 'expired' ? sortedPendingRenewalClients : [...sortedActiveClients, ...sortedPendingRenewalClients];
    setSelectedClientKeys(new Set(list.map(clientRowKey)));
  };
  const deleteSelectedClients = async () => {
    if (!selectedClientKeys.size) return;
    if (!confirm(`${t('deleteSelected')}?`)) return;
    const keys = [...selectedClientKeys];
    setBulkDeleteState({running:true,total:keys.length,done:0,last:''});
    try {
      const chunks = [];
      for (let index = 0; index < keys.length; index += 3) {
        chunks.push(keys.slice(index, index + 3));
      }
      for (const chunk of chunks) {
        const results = await Promise.allSettled(chunk.map(async (entry) => {
          const [serverId, ...rest] = entry.split(':');
          const publicKey = rest.join(':');
          try {
            await deleteClientEntry(publicKey, serverId || activeServerId);
            return {entry, ok:true};
          } catch (error) {
            if (error?.status === 404) return {entry, ok:true, skipped:true};
            throw error;
          }
        }));
        const completed = results.filter(result => result.status === 'fulfilled').length;
        const failed = results.find(result => result.status === 'rejected');
        setBulkDeleteState(current => ({
          ...current,
          done: Math.min(current.total, current.done + completed),
          last: failed ? String(failed.reason?.message || failed.reason || '') : current.last,
        }));
        if (failed) throw failed.reason;
        await new Promise(resolve=>setTimeout(resolve, 0));
      }
      clearClientSelection();
      await load();
    } finally {
      setBulkDeleteState({running:false,total:0,done:0,last:''});
    }
  };
  const clientFieldValue = (client, field) => {
    const stat = clientPeerStat(client);
    switch (field) {
      case 'name':
        return (client.name || '').toLowerCase();
      case 'server':
        return (clientServerName(client) || '').toLowerCase();
      case 'status': {
        const status = clientStatus(client);
        return status.className === 'ok' ? 0 : status.className === 'warn' ? 1 : status.className === 'expired' ? 2 : 3;
      }
      case 'expires':
        return client.expiresAt ? new Date(`${client.expiresAt}T00:00:00`).getTime() : 0;
      case 'lastConnection':
        return stat?.latest || 0;
      case 'blockedAt':
        return client.blockedAt ? new Date(`${client.blockedAt}T00:00:00`).getTime() : 0;
      case 'publicKey':
        return (client.PublicKey || '').toLowerCase();
      case 'allowedIps':
        return (client.AllowedIPs || '').toLowerCase();
      default:
        return 0;
    }
  };
  const sortClients = (list) => {
    const sorted = [...list];
    sorted.sort((a, b) => {
      const av = clientFieldValue(a, clientSortField);
      const bv = clientFieldValue(b, clientSortField);
      if (typeof av === 'number' && typeof bv === 'number') {
        return clientSortDir === 'asc' ? av - bv : bv - av;
      }
      const cmp = String(av).localeCompare(String(bv), undefined, {sensitivity:'base'});
      return clientSortDir === 'asc' ? cmp : -cmp;
    });
    return sorted;
  };
  const setClientSort = (field) => {
    if (clientSortField === field) {
      setClientSortDir(current => current === 'asc' ? 'desc' : 'asc');
      return;
    }
    setClientSortField(field);
    setClientSortDir(field === 'status' || field === 'expires' || field === 'lastConnection' || field === 'blockedAt' ? 'desc' : 'asc');
  };
  const sortIcon = (field) => {
    if (clientSortField !== field) return <ArrowUpDown size={14} />;
    return clientSortDir === 'asc' ? <ArrowUp size={14} /> : <ArrowDown size={14} />;
  };
  const sortedActiveClients = sortClients(activeClientsList);
  const sortedPendingRenewalClients = sortClients(pendingRenewalClients);
  const serverStats = (server)=>{
    const serverClients = server.id === 'all' ? allServerStatsClients : allServerStatsClients.filter(client=>(client.serverId || 'local') === server.id);
    const active = serverClients.filter(client=>!client.blocked).length;
    const created = serverClients.filter(client=>client.createdAt).length;
    const maxUsers = server.id === 'all' ? totalServerMaxUsers : Number(server.maxUsers || 0);
    const keys = new Set(serverClients.map(client=>client.PublicKey));
    const stats = allServerPeerStats.filter(peer=>keys.has(peer.publicKey));
    return {
      total: serverClients.length,
      active,
      created,
      maxUsers,
      rx: stats.reduce((sum,peer)=>sum + peer.rx, 0),
      tx: stats.reduce((sum,peer)=>sum + peer.tx, 0),
    };
  };
  const serverUsageText = (server) => {
    const stats = serverStats(server);
    if (stats.maxUsers > 0) return `${stats.active} / ${stats.maxUsers}`;
    return String(stats.active);
  };
  const serverUsageClass = (server) => {
    const stats = serverStats(server);
    if (!stats.maxUsers) return 'admin';
    return stats.active >= stats.maxUsers ? 'danger' : 'ok';
  };
  const renderClientName=(client)=>{
    const key = clientRowKey(client);
    if (editingClientKey === key) {
      return <div className="inline-edit">
        <input value={editingClientName} onChange={e=>setEditingClientName(e.target.value)} onKeyDown={e=>{ if(e.key==='Enter') renameClient(client).catch(handleError); if(e.key==='Escape') cancelEditClient(); }} autoFocus />
        <button className="secondary icon-button" title={t('save')} onClick={()=>renameClient(client).catch(handleError)}><Check size={16}/></button>
        <button className="secondary icon-button" title={t('cancel')} onClick={cancelEditClient}><X size={16}/></button>
      </div>;
    }
    return <span className="client-name-text">{client.name||'—'}</span>;
  };
  const renderClientActions=(client)=> {
    const key = clientRowKey(client);
    return <div className="client-actions">
      <button className={`secondary icon-button ${isClientSelected(key) ? 'selected' : ''}`} title={isClientSelected(key) ? t('clearSelection') : t('select')} onMouseDown={event=>event.stopPropagation()} onClick={(event)=>{ event.stopPropagation(); toggleClientSelected(client); }}><CheckCircle2 size={16}/></button>
      <button className="secondary icon-button" title={t('details')} onMouseDown={event=>event.stopPropagation()} onClick={(event)=>{ event.stopPropagation(); setExpandedClientKey(expandedClientKey === key ? '' : key); }}><ChevronDown className={expandedClientKey === key ? 'rotated' : ''} size={16}/></button>
      <button className="secondary icon-button" title={t('editName')} onMouseDown={event=>event.stopPropagation()} onClick={(event)=>{ event.stopPropagation(); beginEditClient(client); }}><Pencil size={16}/></button>
      <button className="danger icon-button" title={t('deleteClient')} onMouseDown={event=>event.stopPropagation()} onClick={(event)=>{ event.stopPropagation(); remove(client.PublicKey, client.serverId).catch(handleError); }}><Trash2 size={16}/></button>
    </div>;
  };
  const renderClientDetails=(client, colSpan)=>{
    const stat = clientPeerStat(client);
    return <tr className="detail-row"><td colSpan={colSpan}>
      <div className="detail-panel">
        <div className="detail-title">{client.name || '—'}</div>
        <div className="detail-grid">
          <div><span>{t('lastSeen')}</span><strong>{lastSeenText(client)}</strong></div>
          <div><span>{t('createdOnly')}</span><strong>{formatAnyDate(client.createdAt, lang)}</strong></div>
          <div><span>{t('server')}</span><strong>{clientServerName(client)}</strong></div>
          <div><span>{t('received')}</span><strong>{formatMb(stat?.rx || 0)}</strong></div>
          <div><span>{t('sent')}</span><strong>{formatMb(stat?.tx || 0)}</strong></div>
          <div><span>{t('publicKey')}</span><strong className="mono">{client.PublicKey || '—'}</strong></div>
          <div><span>{t('allowedIps')}</span><strong>{client.AllowedIPs || '—'}</strong></div>
        </div>
        <div className="detail-actions">
          <button className="secondary" onClick={()=>copyClientConfig(client.PublicKey, client.serverId).catch(handleError)}><Clipboard size={16}/>{t('copyConfig')}</button>
          <button className="secondary" onClick={()=>downloadClientConfig(client.PublicKey, client.name||'client', client.serverId).catch(handleError)}><Download size={16}/>{t('download')}</button>
        </div>
      </div>
    </td></tr>;
  };
  const renderServerDetails=(server, colSpan)=>{
    const stats = serverStats(server);
    return <tr className="detail-row"><td colSpan={colSpan}>
      <div className="detail-panel server-detail-panel">
        <div className="detail-grid">
          <div><span>{t('totalClients')}</span><strong>{stats.total}</strong></div>
          <div><span>{t('activeClients')}</span><strong>{stats.maxUsers > 0 ? `${stats.active} / ${stats.maxUsers}` : stats.active}</strong></div>
          <div><span>{t('createdClients')}</span><strong>{stats.created}</strong></div>
          <div><span>{t('received')}</span><strong>{formatMb(stats.rx)}</strong></div>
          <div><span>{t('sent')}</span><strong>{formatMb(stats.tx)}</strong></div>
          <div><span>{t('limit')}</span><strong>{stats.maxUsers > 0 ? stats.maxUsers : '—'}</strong></div>
          <div><span>{t('status')}</span><strong>{serverConnection(server) ? t('active') : t('inactiveEdit')}</strong></div>
        </div>
        <div className="detail-key mono">{server.kind === 'local' || server.id === 'all' ? server.name : server.baseUrl}</div>
      </div>
    </td></tr>;
  };

  if (!isAdminRoute) return <main className="public-page">
    <section className="public-hero">
      <div className="public-hero-copy">
        <h1>{t('appName')}</h1>
        <p>{t('purchaseSub')}</p>
      </div>
      <button className="secondary public-admin-link" onClick={()=>navigate('/admin')}>{t('adminPanel')}</button>
    </section>

    <section className="public-layout">
      <div className="card public-plan-card">
        <div className="panel-head">
          <div>
            <h2>{t('purchase')}</h2>
            <p>{t('purchaseLead')}</p>
          </div>
        </div>
        <div className="public-plans">
          {clientTerms.filter(([value])=>value !== 'admin').map(([value,label])=>(
            <button key={value} type="button" className={orderPlan===dict[uiLang][label] ? 'secondary active' : 'secondary'} onClick={()=>setOrderPlan(dict[uiLang][label])}>
              <strong>{t(label)}</strong>
            </button>
          ))}
        </div>
      </div>
      <div className="card public-order-card">
        <div className="panel-head">
          <div>
            <h2>{t('newOrder')}</h2>
            <p>{t('purchaseOrderSub')}</p>
          </div>
        </div>
        <div className="client-form-grid">
          <label>{t('orderLogin')}<input value={orderLogin} onChange={e=>setOrderLogin(e.target.value)} placeholder={t('orderLoginPlaceholder')} /></label>
          <label>{t('orderEmail')}<input value={orderEmail} onChange={e=>setOrderEmail(e.target.value)} placeholder={t('orderEmailPlaceholder')} /></label>
          <label>{t('term')}<select value={orderPlan} onChange={e=>setOrderPlan(e.target.value)}>
            {clientTerms.filter(([value])=>value !== 'admin').map(([value,label])=><option key={value} value={value}>{t(label)}</option>)}
          </select></label>
        </div>
        <button onClick={()=>addOrder().catch(handleError)} disabled={!orderLogin.trim() || !orderEmail.trim()}><Plus size={16}/>{t('purchaseAction')}</button>
      </div>
    </section>

    {orders.length > 0 && <section className="card">
      <div className="panel-head">
        <div>
          <h2>{t('recentOrders')}</h2>
          <p>{t('allOrders')}: {orders.length}</p>
        </div>
      </div>
      <table className="orders-table"><thead><tr><th>{t('orderLogin')}</th><th>{t('orderEmail')}</th><th>{t('term')}</th><th>{t('status')}</th></tr></thead><tbody>
        {orders.slice(0,5).map(o=><tr key={o.id}>
          <td><strong>{o.login}</strong><small>{t('created')}: {o.created}</small></td>
          <td>{o.email||'—'}</td>
          <td><span className="badge admin">{o.term}</span></td>
          <td><span className={`badge ${orderStatusClass(o.status)}`}>{t(normalizeOrderStatus(o.status))}</span></td>
        </tr>)}
      </tbody></table>
    </section>}
  </main>;

  if(checkingSession) return <main className="auth-page"><section className="card login-card"><h1>{t('appName')}</h1><p>{t('checking')}</p></section></main>;

  if(!isLoggedIn) return <main className="auth-page">
    <section className="card login-card">
      <h1>{t('appName')}</h1>
      <p>{t('signInTitle')}</p>
      <div className="language-switch"><button className={lang==='ru'?'active secondary':'secondary'} onClick={()=>setLanguage('ru')}>RU</button><button className={lang==='us'?'active secondary':'secondary'} onClick={()=>setLanguage('us')}>US</button></div>
      <label>{t('login')}</label>
      <input value={username} onChange={e=>setUsername(e.target.value)} placeholder={t('loginPlaceholder')} autoComplete="username" />
      <label>{t('password')}</label>
      <input value={password} onChange={e=>setPassword(e.target.value)} onKeyDown={e=>{ if(e.key==='Enter') login().catch(handleError); }} placeholder={t('passwordPlaceholder')} type="password" autoComplete="current-password" />
      <button onClick={()=>login().catch(handleError)}><RefreshCw size={16}/>{t('signIn')}</button>
      {error && <pre className="error">{error}</pre>}
    </section>
  </main>;

  return <main className={selectedClientKeys.size > 0 ? 'selection-active' : ''}>
    <header className="topbar">
      <div><h1>{t('appName')}</h1><p>{activeServer?.name || t('noServer')} · {activeServer?.kind === 'local' ? t('localServer') : activeServer?.kind === 'aggregate' ? t('allServers') : (activeServer?.baseUrl || t('noEndpoint'))}</p></div>
      <div className="actions">
        <button className="secondary" onClick={()=>navigate('/')}><Home size={16}/>{t('purchase')}</button>
        <div className="language-switch"><button className={lang==='ru'?'active secondary':'secondary'} onClick={()=>setLanguage('ru')}>RU</button><button className={lang==='us'?'active secondary':'secondary'} onClick={()=>setLanguage('us')}>US</button></div>
        <button disabled={isRefreshing} onClick={()=>load({manual:true}).catch(handleError)}><RefreshCw size={16}/>{isRefreshing?t('refreshing'):t('refresh')}</button>
        <button className="secondary" onClick={logout}><LogOut size={16}/>{t('logout')}</button>
      </div>
    </header>

    <nav className="menu">
      {nav.map(([id,label,Icon])=><button key={id} className={view===id?'active secondary':'secondary'} onClick={()=>setView(id)}><Icon size={17}/>{label}</button>)}
    </nav>

    {error && <pre className="error">{error}</pre>}
    {notice && <div className="notice">{notice}</div>}

    {view==='home' && <>
      <section className="dashboard-grid">
        <div className="card metric"><Users size={22}/><span>{t('totalClients')}</span><strong>{clients.length}</strong></div>
        <div className="card metric"><Activity size={22}/><span>{t('activeClients')}</span><strong>{activeClientCount}</strong></div>
        <div className="card metric"><ShoppingCart size={22}/><span>{t('orders')}</span><strong>{orders.length}</strong></div>
        <div className="card metric"><Server size={22}/><span>{t('serversActive')}</span><strong>{servers.length} / {activeServerCount}</strong></div>
      </section>
      <section className="home-layout">
        <div className="card chart-card">
          <div className="panel-head"><div><h2>{t('activeUsers')}</h2><p>{t('maxOnline')}</p></div><span className="badge ok">{t('now')}: {activeClientCount}</span></div>
          <ActivityChart points={activityHistory} lang={lang}/>
          <div className="chart-labels">{chartDays(activityHistory).map(point=><span key={point.date}>{dateLabel(point.date, lang)}</span>)}</div>
        </div>
        <div className="card traffic-card">
          <h2>{t('traffic')}</h2>
          <div className="traffic-row"><span>{t('rx')}</span><strong>{formatMb(totalRx)}</strong></div>
          <div className="traffic-row"><span>{t('tx')}</span><strong>{formatMb(totalTx)}</strong></div>
          <div className="traffic-row muted"><span>{t('peersDump')}</span><strong>{peerStats.length}</strong></div>
        </div>
      </section>
    </>}

      {view==='clients' && <>
      <section className="section-head">
        <div><h2>{t('clients')}</h2><p>{t('clientsSub')}</p></div>
        <div className="actions">
          <button className={activeServerId==='all'?'secondary active':'secondary'} onClick={()=>selectServer('all')}>{t('allServers')}</button>
          <button className="secondary" onClick={()=>setShowImportForm(true)}><Upload size={16}/>{t('importConf')}</button>
          <button onClick={()=>setShowClientForm(true)}><Plus size={16}/>{t('createClient')}</button>
        </div>
      </section>

      {selectedClientKeys.size > 0 && <details className="selection-drop" open>
        <summary>
          <div className="selection-drop-summary">
            <strong>{t('selectedClients')}: {selectedClientKeys.size}</strong>
            <span>{bulkDeleteState.running ? `${t('deleted')}: ${bulkDeleteState.done} / ${bulkDeleteState.total}` : t('bulkActions')}</span>
          </div>
          <ChevronDown size={16}/>
        </summary>
        <div className="selection-drop-body">
          <div className="selection-progress">
            <div className="selection-progress-track">
              <span style={{width: `${bulkDeleteState.total ? (bulkDeleteState.done / bulkDeleteState.total) * 100 : 0}%`}} />
            </div>
            <small>{bulkDeleteState.running ? `${t('deleting')}: ${bulkDeleteState.done}/${bulkDeleteState.total}` : t('bulkReady')}</small>
          </div>
          <div className="selection-drop-actions">
            <button className="secondary" onClick={selectAllVisibleClients}><CheckCircle2 size={16}/>{t('selectAll')}</button>
            <button className="secondary" onClick={clearClientSelection}><X size={16}/>{t('clearSelection')}</button>
            <button className="danger" disabled={bulkDeleteState.running} onClick={()=>deleteSelectedClients().catch(handleError)}><Trash2 size={16}/>{t('deleteSelected')}</button>
          </div>
          {bulkDeleteState.last && <div className="selection-drop-error">{bulkDeleteState.last}</div>}
        </div>
      </details>}

      {showImportForm && <section className="card add-panel">
        <div className="panel-head">
          <h2>{t('importTitle')}</h2>
          <button className="secondary" onClick={()=>setShowImportForm(false)}>{t('close')}</button>
        </div>
        <div className="client-form-grid">
          <label>{t('clientName')}<input value={importName} onChange={e=>setImportName(e.target.value)} placeholder={t('importNamePlaceholder')} /></label>
        </div>
        <label>{t('readyConf')}<textarea value={importConfig} onChange={e=>setImportConfig(e.target.value)} placeholder="[Interface]&#10;PrivateKey = ...&#10;Address = ...&#10;&#10;[Peer]&#10;PublicKey = ..." /></label>
        <button onClick={()=>importClient().catch(handleError)} disabled={!importConfig.trim()}><Upload size={16}/>{t('saveCopy')}</button>
      </section>}

      {showClientForm && <section className="card add-panel">
        <div className="panel-head">
          <h2>{t('createClient')}</h2>
          <button className="secondary" onClick={()=>setShowClientForm(false)}>{t('close')}</button>
        </div>
        <div className="client-form-grid">
          <label>{t('clientName')}<input value={name} onChange={e=>setName(e.target.value)} placeholder={t('clientNamePlaceholder')} /></label>
          <label>{t('server')}<select value={clientServerId} onChange={e=>setClientServerId(e.target.value)}>
            {servers.map(server=><option key={server.id} value={server.id}>{server.name} · {server.kind === 'local' ? t('localServer') : server.baseUrl}</option>)}
          </select></label>
          <label>{t('term')}<select value={clientTerm} onChange={e=>setClientTerm(e.target.value)}>
            {clientTerms.map(([value,label])=><option key={value} value={value}>{t(label)}</option>)}
          </select></label>
        </div>
        <button onClick={()=>create().catch(handleError)}><Plus size={16}/>{t('createIssue')}</button>
      </section>}

      {selectedConfig && <section className="card issued-config">
        <div className="panel-head">
          <h2>{t('issuedConf')}</h2>
          <button className="secondary" onClick={closeIssuedConfig}>{t('close')}</button>
        </div>
        <pre>{selectedConfig}</pre>
      </section>}

      <section className="card">
        <div className="panel-head"><div><h2>{t('activeClients')}</h2><p>{t('activeClientsSub')}</p></div><span className="badge ok">{activeClientsList.length}</span></div>
        <table className="client-table active-client-table"><thead><tr><th><button type="button" className={`table-sort ${clientSortField==='name' ? 'active' : ''}`} onClick={()=>setClientSort('name')}>{t('name')}{sortIcon('name')}</button></th><th><button type="button" className={`table-sort ${clientSortField==='server' ? 'active' : ''}`} onClick={()=>setClientSort('server')}>{t('server')}{sortIcon('server')}</button></th><th><button type="button" className={`table-sort ${clientSortField==='status' ? 'active' : ''}`} onClick={()=>setClientSort('status')}>{t('status')}{sortIcon('status')}</button></th><th><button type="button" className={`table-sort ${clientSortField==='expires' ? 'active' : ''}`} onClick={()=>setClientSort('expires')}>{t('expires')}{sortIcon('expires')}</button></th><th><button type="button" className={`table-sort ${clientSortField==='lastConnection' ? 'active' : ''}`} onClick={()=>setClientSort('lastConnection')}>{t('lastConnection')}{sortIcon('lastConnection')}</button></th><th></th></tr></thead><tbody>
          {sortedActiveClients.map(c=>{ const key = clientRowKey(c); const status = clientStatus(c); return <React.Fragment key={key}><tr className={`clickable-row ${expandedClientKey === key ? 'expanded' : ''} ${isClientSelected(key) ? 'selected-row' : ''}`} onMouseDown={event=>beginClientSelectionDrag(c, event)} onMouseEnter={()=>continueClientSelectionDrag(c)} onClick={()=>{ if (selectionDragRef.current.suppressClick) return; setExpandedClientKey(expandedClientKey === key ? '' : key); }}>
            <td onClick={event=>event.stopPropagation()}>{renderClientName(c)}</td>
            <td>{clientServerName(c)}</td>
            <td><span className={`badge ${status.className}`}>{status.label}</span></td>
            <td>{c.expiresAt ? <span className={`badge ${isExpired(c.expiresAt) ? 'expired' : 'muted'}`}>{formatDate(c.expiresAt, lang)}</span> : <span className="badge admin">{t('admin')}</span>}</td>
            <td>{lastSeenText(c)}</td>
            <td className="table-actions">{renderClientActions(c)}</td>
          </tr>{expandedClientKey === key && renderClientDetails(c, 6)}</React.Fragment> })}
        </tbody></table>
      </section>

      {pendingRenewalClients.length > 0 && <section className="card">
        <div className="panel-head"><div><h2>{t('expiredClients')}</h2><p>{t('expiredClientsSub')}</p></div><span className="badge expired">{pendingRenewalClients.length}</span></div>
        <table className="client-table expired-client-table"><thead><tr><th><button type="button" className={`table-sort ${clientSortField==='name' ? 'active' : ''}`} onClick={()=>setClientSort('name')}>{t('name')}{sortIcon('name')}</button></th><th><button type="button" className={`table-sort ${clientSortField==='server' ? 'active' : ''}`} onClick={()=>setClientSort('server')}>{t('server')}{sortIcon('server')}</button></th><th><button type="button" className={`table-sort ${clientSortField==='status' ? 'active' : ''}`} onClick={()=>setClientSort('status')}>{t('status')}{sortIcon('status')}</button></th><th><button type="button" className={`table-sort ${clientSortField==='expires' ? 'active' : ''}`} onClick={()=>setClientSort('expires')}>{t('expires')}{sortIcon('expires')}</button></th><th><button type="button" className={`table-sort ${clientSortField==='lastConnection' ? 'active' : ''}`} onClick={()=>setClientSort('lastConnection')}>{t('lastConnection')}{sortIcon('lastConnection')}</button></th><th><button type="button" className={`table-sort ${clientSortField==='blockedAt' ? 'active' : ''}`} onClick={()=>setClientSort('blockedAt')}>{t('blockedAt')}{sortIcon('blockedAt')}</button></th><th></th></tr></thead><tbody>
          {sortedPendingRenewalClients.map(c=>{ const key = clientRowKey(c); return <React.Fragment key={key}><tr className={`clickable-row ${expandedClientKey === key ? 'expanded' : ''} ${isClientSelected(key) ? 'selected-row' : ''}`} onMouseDown={event=>beginClientSelectionDrag(c, event)} onMouseEnter={()=>continueClientSelectionDrag(c)} onClick={()=>{ if (selectionDragRef.current.suppressClick) return; setExpandedClientKey(expandedClientKey === key ? '' : key); }}>
            <td onClick={event=>event.stopPropagation()}>{renderClientName(c)}</td>
            <td>{clientServerName(c)}</td>
            <td><span className="badge expired">{t('renewalPending')}</span></td>
            <td>{c.expiresAt ? formatDate(c.expiresAt, lang) : <span className="badge admin">{t('admin')}</span>}</td>
            <td>{lastSeenText(c)}</td>
            <td>{c.blockedAt ? formatDate(c.blockedAt, lang) : '—'}</td>
            <td className="table-actions">{renderClientActions(c)}</td>
          </tr>{expandedClientKey === key && renderClientDetails(c, 7)}</React.Fragment>})}
        </tbody></table>
      </section>}
    </>}

    {view==='expired' && <>
      <section className="section-head">
        <div><h2>{t('expiredClients')}</h2><p>{t('expiredClientsSub')}</p></div>
        <span className="badge expired">{pendingRenewalClients.length}</span>
      </section>
      <section className="card">
        <table className="client-table expired-client-table"><thead><tr><th><button type="button" className={`table-sort ${clientSortField==='name' ? 'active' : ''}`} onClick={()=>setClientSort('name')}>{t('name')}{sortIcon('name')}</button></th><th><button type="button" className={`table-sort ${clientSortField==='server' ? 'active' : ''}`} onClick={()=>setClientSort('server')}>{t('server')}{sortIcon('server')}</button></th><th><button type="button" className={`table-sort ${clientSortField==='status' ? 'active' : ''}`} onClick={()=>setClientSort('status')}>{t('status')}{sortIcon('status')}</button></th><th><button type="button" className={`table-sort ${clientSortField==='expires' ? 'active' : ''}`} onClick={()=>setClientSort('expires')}>{t('expires')}{sortIcon('expires')}</button></th><th><button type="button" className={`table-sort ${clientSortField==='lastConnection' ? 'active' : ''}`} onClick={()=>setClientSort('lastConnection')}>{t('lastConnection')}{sortIcon('lastConnection')}</button></th><th><button type="button" className={`table-sort ${clientSortField==='blockedAt' ? 'active' : ''}`} onClick={()=>setClientSort('blockedAt')}>{t('blockedAt')}{sortIcon('blockedAt')}</button></th><th></th></tr></thead><tbody>
          {sortedPendingRenewalClients.map(c=>{ const key = clientRowKey(c); return <React.Fragment key={key}><tr className={`clickable-row ${expandedClientKey === key ? 'expanded' : ''} ${isClientSelected(key) ? 'selected-row' : ''}`} onMouseDown={event=>beginClientSelectionDrag(c, event)} onMouseEnter={()=>continueClientSelectionDrag(c)} onClick={()=>{ if (selectionDragRef.current.suppressClick) return; setExpandedClientKey(expandedClientKey === key ? '' : key); }}>
            <td onClick={event=>event.stopPropagation()}>{renderClientName(c)}</td>
            <td>{clientServerName(c)}</td>
            <td><span className="badge expired">{t('renewalPending')}</span></td>
            <td>{c.expiresAt ? formatDate(c.expiresAt, lang) : <span className="badge admin">{t('admin')}</span>}</td>
            <td>{lastSeenText(c)}</td>
            <td>{c.blockedAt ? formatDate(c.blockedAt, lang) : '—'}</td>
            <td className="table-actions">{renderClientActions(c)}</td>
          </tr>{expandedClientKey === key && renderClientDetails(c, 7)}</React.Fragment>})}
        </tbody></table>
      </section>
    </>}

    {view==='orders' && <>
      <section className="section-head">
        <div><h2>{t('orders')}</h2><p>{t('ordersSub')}</p></div>
        <span className="badge ok">{t('allOrders')}: {orders.length}</span>
      </section>

      <section className="order-stats">
        {orderStatuses.map(([status,label,Icon])=><div className="card order-stat" key={status}>
          <Icon size={20}/>
          <span>{t(label)}</span>
          <strong>{orderCounts[status] || 0}</strong>
        </div>)}
      </section>

      <section className="card add-panel">
        <div className="panel-head"><div><h2>{t('newOrder')}</h2><p>{t('ordersSub')}</p></div></div>
        <div className="order-form-grid">
          <label>{t('orderLogin')}<input value={orderLogin} onChange={e=>setOrderLogin(e.target.value)} placeholder={t('orderLoginPlaceholder')} /></label>
          <label>{t('orderEmail')}<input value={orderEmail} onChange={e=>setOrderEmail(e.target.value)} placeholder={t('orderEmailPlaceholder')} /></label>
          <label>{t('term')}<select value={orderPlan} onChange={e=>setOrderPlan(e.target.value)}>
            <option>{t('oneMonth')}</option><option>{t('threeMonths')}</option><option>{t('sixMonths')}</option><option>{t('oneYear')}</option>
          </select></label>
        </div>
        <button onClick={()=>addOrder().catch(handleError)} disabled={!orderLogin.trim() || !orderEmail.trim()}><Plus size={16}/>{t('add')}</button>
      </section>

      <section className="card">
        <div className="panel-head"><div><h2>{t('recentOrders')}</h2><p>{t('allOrders')}: {orders.length}</p></div></div>
        {orders.length === 0 ? <p>{t('noOrders')}</p> : <table className="orders-table"><thead><tr><th>{t('orderLogin')}</th><th>{t('orderEmail')}</th><th>{t('term')}</th><th>{t('status')}</th><th></th></tr></thead><tbody>
          {orders.map(o=>{ const normalizedStatus = normalizeOrderStatus(o.status); return <tr key={o.id}>
            <td><strong>{o.login}</strong><small>{t('created')}: {o.created}</small></td>
            <td>{o.email||'—'}</td>
            <td><span className="badge admin">{o.term}</span></td>
            <td>
              <span className={`badge ${orderStatusClass(o.status)}`}>{t(normalizedStatus)}</span>
              <select value={normalizedStatus} onChange={e=>updateOrder(o.id,e.target.value)} aria-label={t('status')}>
                {orderStatuses.map(([value,label])=><option key={value} value={value}>{t(label)}</option>)}
              </select>
            </td>
            <td className="table-actions"><button className="danger" onClick={()=>deleteOrder(o.id)}><Trash2 size={16}/></button></td>
          </tr> })}
        </tbody></table>}
      </section>
    </>}

    {view==='server' && <>
      <section className="section-head">
        <div><h2>{t('servers')}</h2><p>{t('serversSub')}</p></div>
        <div className="actions">
          <button className={activeServerId==='all'?'secondary active':'secondary'} onClick={()=>selectServer('all')}>{t('allServers')}</button>
          <button onClick={()=>setShowServerForm(true)}><Plus size={16}/>{t('addServer')}</button>
        </div>
      </section>
      <section className="server-summary">
        <div className="card metric server-metric"><Server size={22}/><span>{t('servers')}</span><strong>{servers.length}</strong></div>
        <div className="card metric server-metric"><Activity size={22}/><span>{t('activeClients')}</span><strong>{totalServerMaxUsers > 0 ? `${activeClientTotal} / ${totalServerMaxUsers}` : activeClientTotal}</strong></div>
        <div className="card metric server-metric"><Users size={22}/><span>{t('clients')}</span><strong>{allServerStatsClients.length}</strong></div>
        <div className="card metric server-metric"><ShoppingCart size={22}/><span>{t('traffic')}</span><strong>{formatMb(allServerTotalRx + allServerTotalTx)}</strong></div>
      </section>
      {showServerForm && <section className="card add-panel">
        <div className="panel-head">
          <h2>{editingServerId?t('editServer'):t('addServer')}</h2>
          <button className="secondary" onClick={closeServerForm}>{t('close')}</button>
        </div>
        <div className="server-form-grid">
          <label>{t('title')}<input value={serverName} onChange={e=>setServerName(e.target.value)} placeholder={t('serverNamePlaceholder')} /></label>
          {!editingLocalServer && <label>{t('panelUrl')}<input value={serverBaseUrl} onChange={e=>setServerBaseUrl(e.target.value)} placeholder={t('panelUrlPlaceholder')} /></label>}
          {!editingLocalServer && <label>{t('token')}<input value={serverToken} onChange={e=>setServerToken(e.target.value)} placeholder={t('token')} type="password" /></label>}
          <label>{t('limit')}<input value={serverMaxUsers} onChange={e=>setServerMaxUsers(e.target.value)} placeholder="0" type="number" min="0" inputMode="numeric" /></label>
        </div>
        <button onClick={()=>addServer().catch(handleError)}><Plus size={16}/>{t('saveServer')}</button>
      </section>}
      <section className="card">
        <table className="server-table"><thead><tr><th>{t('title')}</th><th>{t('endpoint')}</th><th>{t('token')}</th><th>{t('status')}</th><th>{t('activeClients')}</th><th>{t('limit')}</th><th></th></tr></thead><tbody>
          {(()=>{ const server = {id:'all', name:t('allServers'), baseUrl:'', kind:'aggregate', status:'online'}; return <React.Fragment key="all"><tr className={`clickable-row ${activeServerId==='all'?'selected-row':''} ${expandedServerId === 'all' ? 'expanded' : ''}`} onClick={()=>setExpandedServerId(expandedServerId === 'all' ? '' : 'all')}>
            <td><strong>{t('allServers')}</strong>{activeServerId==='all' && <small>{t('activeServer')}</small>}</td>
            <td className="mono">—</td>
            <td><span className="badge ok">{t('set')}</span></td>
            <td><span className="badge ok">{t('active')}</span></td>
            <td><span className={`badge ${serverUsageClass(server)}`}>{serverUsageText(server)}</span></td>
            <td className="mono">—</td>
            <td className="table-actions"><button className="secondary icon-button" title={t('details')} onClick={(event)=>{ event.stopPropagation(); setExpandedServerId(expandedServerId === 'all' ? '' : 'all'); }}><ChevronDown className={expandedServerId === 'all' ? 'rotated' : ''} size={16}/></button><button className="secondary" onClick={(event)=>{ event.stopPropagation(); selectServer('all'); }}>{t('select')}</button></td>
          </tr>{expandedServerId === 'all' && renderServerDetails(server, 7)}</React.Fragment>; })()}
          {servers.map(s=><React.Fragment key={s.id}><tr className={`clickable-row ${s.id===activeServerId?'selected-row':''} ${expandedServerId === s.id ? 'expanded' : ''}`} onClick={()=>setExpandedServerId(expandedServerId === s.id ? '' : s.id)}>
            <td><strong>{s.name}</strong>{s.id===activeServerId && <small>{t('activeServer')}</small>}</td>
            <td className="mono">{s.kind === 'local' ? t('localServer') : s.baseUrl}</td>
            <td>{s.kind === 'local' ? <span className="badge ok">{t('set')}</span> : (s.token ? <span className="badge ok">{t('set')}</span> : <span className="badge muted">{t('notSet')}</span>)}</td>
            <td>{serverConnection(s)?<span className="badge ok">{t('active')}</span>:<span className="badge warn">{t('inactiveEdit')}</span>}</td>
            <td><span className={`badge ${serverUsageClass(s)}`}>{serverUsageText(s)}</span></td>
            <td>
              {s.id === 'all' ? '—' : <input className="server-limit-input" type="number" min="0" inputMode="numeric" value={serverLimitValue(s)} onChange={e=>setServerLimitDrafts(current=>({...current, [s.id]: e.target.value}))} onBlur={e=>saveServerLimit(s, e.target.value).catch(handleError)} onKeyDown={e=>{ if (e.key === 'Enter') e.currentTarget.blur(); }} />}
            </td>
            <td className="table-actions"><button className="secondary icon-button" title={t('details')} onClick={(event)=>{ event.stopPropagation(); setExpandedServerId(expandedServerId === s.id ? '' : s.id); }}><ChevronDown className={expandedServerId === s.id ? 'rotated' : ''} size={16}/></button><button className="secondary" onClick={(event)=>{ event.stopPropagation(); selectServer(s.id); }}>{t('select')}</button><button className="secondary icon-button" title={t('edit')} onClick={(event)=>{ event.stopPropagation(); editServer(s); }}><Pencil size={16}/></button>{s.id !== 'local' && <button className="danger icon-button" title={t('deleteServer')} onClick={(event)=>{ event.stopPropagation(); deleteServer(s.id); }}><Trash2 size={16}/></button>}</td>
          </tr>{expandedServerId === s.id && renderServerDetails(s, 7)}</React.Fragment>)}
        </tbody></table>
      </section>
      <section className="card"><h2>{t('dumpTitle')}</h2><pre>{dump||t('noDump')}</pre></section>
    </>}

  </main>
}

createRoot(document.getElementById('root')).render(<App/>);
