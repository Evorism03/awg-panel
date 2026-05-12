import React, {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Activity, Download, Home, LogOut, Plus, RefreshCw, Server, ShoppingCart, Trash2, Users} from 'lucide-react';
import './style.css';

const api = async (path, options={}) => {
  const res = await fetch(path, { ...options, credentials:'same-origin', headers: { 'Content-Type':'application/json', ...(options.headers||{}) }});
  if (!res.ok) {
    if (res.status === 401) throw new Error('Неверный логин или пароль.');
    throw new Error(await res.text());
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
const dateLabel = (key) => {
  const today = dateKey();
  if (key === today) return 'Сегодня';
  return new Date(`${key}T00:00:00`).toLocaleDateString('ru-RU', {day:'2-digit', month:'2-digit'});
};

const smoothPath = (coords) => {
  if (coords.length < 2) return coords[0] ? `M ${coords[0].x} ${coords[0].y}` : '';
  return coords.reduce((path, point, index, points) => {
    if (index === 0) return `M ${point.x} ${point.y}`;
    const previous = points[index - 1];
    const controlX = (previous.x + point.x) / 2;
    return `${path} C ${controlX} ${previous.y}, ${controlX} ${point.y}, ${point.x} ${point.y}`;
  }, '');
};

function ActivityChart({points}) {
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
      {data[index].date <= today && <title>{dateLabel(data[index].date)}: {data[index].value} онлайн</title>}
    </g>)}
  </svg>;
}

function chartDays(points) {
  const today = dateKey();
  const byDate = Object.fromEntries(points.map(point=>[point.date, point.value]));
  return Array.from({length:10}, (_,index)=>shiftDateKey(today, index - 5)).map(date=>({date, value:byDate[date] || 0}));
}

function App(){
  const [view,setView]=useState('home');
  const [username,setUsername]=useState('admin');
  const [password,setPassword]=useState('');
  const [isLoggedIn,setIsLoggedIn]=useState(false);
  const [checkingSession,setCheckingSession]=useState(true);
  const [isLoading,setIsLoading]=useState(false);
  const [notice,setNotice]=useState('');
  const [refreshSeq,setRefreshSeq]=useState(0);
  const [clients,setClients]=useState([]);
  const [dump,setDump]=useState('');
  const [name,setName]=useState('');
  const [showClientForm,setShowClientForm]=useState(false);
  const [clientServerId,setClientServerId]=useState(()=>localStorage.getItem('activeServerId')||'main');
  const [clientConfigs,setClientConfigs]=useState(()=>JSON.parse(localStorage.getItem('clientConfigs')||'{}'));
  const [selectedQr,setSelectedQr]=useState('');
  const [selectedConfig,setSelectedConfig]=useState('');
  const [showServerForm,setShowServerForm]=useState(false);
  const [serverName,setServerName]=useState('');
  const [serverIp,setServerIp]=useState('');
  const [serverPort,setServerPort]=useState('');
  const [serverToken,setServerToken]=useState('');
  const [editingServerId,setEditingServerId]=useState(null);
  const [activeServerId,setActiveServerId]=useState(()=>localStorage.getItem('activeServerId')||'main');
  const [servers,setServers]=useState(()=>JSON.parse(localStorage.getItem('servers')||'[{"id":"main","name":"Основной VPS","ip":"45.15.152.113","port":"47074","token":"","status":"active"}]'));
  const [orderName,setOrderName]=useState('');
  const [orderContact,setOrderContact]=useState('');
  const [orderPlan,setOrderPlan]=useState('1 месяц');
  const [orders,setOrders]=useState(()=>JSON.parse(localStorage.getItem('orders')||'[]'));
  const [activityHistory,setActivityHistory]=useState(()=>JSON.parse(localStorage.getItem('dailyActivityHistory')||'[]'));
  const [lastConfig,setLastConfig]=useState('');
  const [qr,setQr]=useState('');
  const [error,setError]=useState('');

  const handleError=(e)=>{
    setError(e.message);
    if (e.message.includes('логин') || e.message.includes('пароль')) {
      setIsLoggedIn(false);
      setClients([]);
      setDump('');
    }
  };

  const load=async({manual=false}={})=>{
    setIsLoading(true);
    setError('');
    try {
      const r=await api('/api/clients');
      const j=await r.json();
      setClients(j.clients||[]); setDump(j.dump||'');
      setRefreshSeq(seq=>seq + 1);
      setIsLoggedIn(true);
      if (manual) {
        setNotice('Данные обновлены');
        setTimeout(()=>setNotice(''), 2500);
      }
    } finally {
      setIsLoading(false);
    }
  };

  const login=async()=>{
    setError('');
    await api('/api/login',{method:'POST',body:JSON.stringify({username:username.trim(),password})});
    setPassword('');
    await load();
  };

  const saveClientConfig=(publicKey, config)=>{
    const next = {...clientConfigs, [publicKey]: config};
    setClientConfigs(next);
    localStorage.setItem('clientConfigs', JSON.stringify(next));
  };
  const create=async()=>{
    const targetServer = servers.find(s=>s.id===clientServerId);
    if(!targetServer || !serverConnection(targetServer)){
      setError('Выбранный сервер недоступен. Выбери активный сервер или отредактируй подключение.');
      return;
    }
    const r=await api('/api/clients',{method:'POST',body:JSON.stringify({name})});
    const j=await r.json(); setLastConfig(j.config); saveClientConfig(j.publicKey, j.config); setName(''); setShowClientForm(false); await load();
    const qrRes=await api('/api/qrcode',{method:'POST',body:JSON.stringify({config:j.config})});
    const qrUrl = URL.createObjectURL(await qrRes.blob());
    setQr(qrUrl);
    setSelectedQr(qrUrl);
    setSelectedConfig(j.config);
  };

  const remove=async(pk)=>{ if(!confirm('Удалить клиента?')) return; await api('/api/clients/'+encodeURIComponent(pk),{method:'DELETE'}); await load(); };
  const downloadConfig=(config, filename='amneziawg-client.conf')=>{ const a=document.createElement('a'); a.href=URL.createObjectURL(new Blob([config],{type:'text/plain'})); a.download=filename; a.click(); };
  const download=()=>downloadConfig(lastConfig);
  const showQr=async(config)=>{
    setSelectedConfig(config);
    const qrRes=await api('/api/qrcode',{method:'POST',body:JSON.stringify({config})});
    setSelectedQr(URL.createObjectURL(await qrRes.blob()));
  };
  const copyKey=async(key)=>{ await navigator.clipboard.writeText(key); setNotice('Ключ скопирован'); setTimeout(()=>setNotice(''), 2000); };
  const closeIssuedConfig=()=>{ setSelectedQr(''); setSelectedConfig(''); setLastConfig(''); setQr(''); };
  const logout=async()=>{ await api('/api/logout',{method:'POST'}).catch(()=>{}); setIsLoggedIn(false); setClients([]); setDump(''); setError(''); setNotice(''); };
  const saveServers=(next)=>{ setServers(next); localStorage.setItem('servers',JSON.stringify(next)); };
  const addServer=()=>{
    if(!serverName.trim() || !serverIp.trim() || !serverPort.trim()) return;
    if(editingServerId){
      saveServers(servers.map(s=>s.id===editingServerId?{...s,name:serverName.trim(),ip:serverIp.trim(),port:serverPort.trim(),token:serverToken.trim()}:s));
    } else {
      const id = crypto.randomUUID();
      saveServers([...servers,{id,name:serverName.trim(),ip:serverIp.trim(),port:serverPort.trim(),token:serverToken.trim()}]);
      setActiveServerId(id);
      localStorage.setItem('activeServerId',id);
    }
    setServerName(''); setServerIp(''); setServerPort(''); setServerToken(''); setShowServerForm(false);
    setEditingServerId(null);
  };
  const selectServer=(id)=>{ setActiveServerId(id); localStorage.setItem('activeServerId',id); };
  const editServer=(server)=>{
    setEditingServerId(server.id);
    setServerName(server.name);
    setServerIp(server.ip || server.endpoint?.split(':')[0] || '');
    setServerPort(server.port || server.endpoint?.split(':')[1] || '');
    setServerToken(server.token || '');
    setShowServerForm(true);
  };
  const closeServerForm=()=>{
    setShowServerForm(false);
    setEditingServerId(null);
    setServerName('');
    setServerIp('');
    setServerPort('');
    setServerToken('');
  };
  const deleteServer=(id)=>{
    const next = servers.filter(s=>s.id!==id);
    saveServers(next);
    if(activeServerId===id && next[0]) selectServer(next[0].id);
  };
  const saveOrders=(next)=>{ setOrders(next); localStorage.setItem('orders',JSON.stringify(next)); };
  const addOrder=()=>{
    const title = orderName.trim();
    if(!title) return;
    saveOrders([{id:crypto.randomUUID(), name:title, contact:orderContact.trim(), plan:orderPlan, status:'Новый', created:new Date().toLocaleString('ru-RU')}, ...orders]);
    setOrderName(''); setOrderContact('');
  };
  const updateOrder=(id,status)=>saveOrders(orders.map(o=>o.id===id?{...o,status}:o));
  const deleteOrder=(id)=>saveOrders(orders.filter(o=>o.id!==id));

  useEffect(()=>{ load().catch(()=>setIsLoggedIn(false)).finally(()=>setCheckingSession(false)); },[]);

  const nav = [
    ['home','Главная',Home],
    ['clients','Клиенты',Users],
    ['orders','Заказы',ShoppingCart],
    ['server','Серверы',Server],
  ];
  const authed = isLoggedIn;
  const activeServer = servers.find(s=>s.id===activeServerId) || servers[0];
  const serverConnection = (server)=>server.id==='main' && authed && Boolean(dump || clients.length);
  const peerStats = parsePeerStats(dump);
  const peerStatsByKey = Object.fromEntries(peerStats.map(peer=>[peer.publicKey, peer]));
  const nowSeconds = Math.floor(Date.now() / 1000);
  const activeClientCount = peerStats.filter(peer=>peer.latest && nowSeconds - peer.latest < 60).length;
  const totalRx = peerStats.reduce((sum,peer)=>sum + peer.rx, 0);
  const totalTx = peerStats.reduce((sum,peer)=>sum + peer.tx, 0);
  const activeServerCount = servers.filter(serverConnection).length;

  useEffect(()=>{
    if(!isLoggedIn) return;
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
  },[isLoggedIn, activeClientCount, refreshSeq]);

  useEffect(()=>{
    if(!isLoggedIn) return;
    const timer = setInterval(()=>load().catch(handleError), 5000);
    return ()=>clearInterval(timer);
  },[isLoggedIn]);

  const clientStatus = (publicKey)=>{
    const stat = peerStatsByKey[publicKey];
    if(!stat?.latest) return {label:'Оффлайн', className:'muted'};
    const age = nowSeconds - stat.latest;
    if(age < 60) return {label:'Онлайн', className:'ok'};
    if(age < 900) return {label:'Недавно', className:'warn'};
    return {label:'Оффлайн', className:'muted'};
  };

  if(checkingSession) return <main className="auth-page"><section className="card login-card"><h1>AmneziaWG Admin</h1><p>Проверка сессии</p></section></main>;

  if(!isLoggedIn) return <main className="auth-page">
    <section className="card login-card">
      <h1>AmneziaWG Admin</h1>
      <p>Вход в панель управления</p>
      <label>Логин</label>
      <input value={username} onChange={e=>setUsername(e.target.value)} placeholder="admin" autoComplete="username" />
      <label>Пароль</label>
      <input value={password} onChange={e=>setPassword(e.target.value)} onKeyDown={e=>{ if(e.key==='Enter') login().catch(handleError); }} placeholder="admin123" type="password" autoComplete="current-password" />
      <button onClick={()=>login().catch(handleError)}><RefreshCw size={16}/>Войти</button>
      {error && <pre className="error">{error}</pre>}
    </section>
  </main>;

  return <main>
    <header className="topbar">
      <div><h1>AmneziaWG Admin</h1><p>{activeServer?.name || 'Сервер не выбран'} · {activeServer ? `${activeServer.ip}:${activeServer.port}` : 'endpoint не задан'}</p></div>
      <div className="actions">
        <button disabled={isLoading} onClick={()=>load({manual:true}).catch(handleError)}><RefreshCw size={16}/>{isLoading?'Обновление':'Обновить'}</button>
        <button className="secondary" onClick={logout}><LogOut size={16}/>Выйти</button>
      </div>
    </header>

    <nav className="menu">
      {nav.map(([id,label,Icon])=><button key={id} className={view===id?'active secondary':'secondary'} onClick={()=>setView(id)}><Icon size={17}/>{label}</button>)}
    </nav>

    {error && <pre className="error">{error}</pre>}
    {notice && <div className="notice">{notice}</div>}

    {view==='home' && <>
      <section className="dashboard-grid">
        <div className="card metric"><Users size={22}/><span>Всего клиентов</span><strong>{clients.length}</strong></div>
        <div className="card metric"><Activity size={22}/><span>Активные клиенты</span><strong>{activeClientCount}</strong></div>
        <div className="card metric"><ShoppingCart size={22}/><span>Заказы</span><strong>{orders.length}</strong></div>
        <div className="card metric"><Server size={22}/><span>Серверы / активные</span><strong>{servers.length} / {activeServerCount}</strong></div>
      </section>
      <section className="home-layout">
        <div className="card chart-card">
          <div className="panel-head"><div><h2>Активные пользователи</h2><p>Максимум онлайн-клиентов по дням</p></div><span className="badge ok">Сейчас: {activeClientCount}</span></div>
          <ActivityChart points={activityHistory}/>
          <div className="chart-labels">{chartDays(activityHistory).map(point=><span key={point.date}>{dateLabel(point.date)}</span>)}</div>
        </div>
        <div className="card traffic-card">
          <h2>Трафик</h2>
          <div className="traffic-row"><span>Прием данных</span><strong>{formatMb(totalRx)}</strong></div>
          <div className="traffic-row"><span>Отдача данных</span><strong>{formatMb(totalTx)}</strong></div>
          <div className="traffic-row muted"><span>Peers в dump</span><strong>{peerStats.length}</strong></div>
        </div>
      </section>
    </>}

    {view==='clients' && <>
      <section className="section-head">
        <div><h2>Клиенты</h2><p>Создание, выдача конфигов и QR-кодов для выбранного сервера</p></div>
        <button onClick={()=>setShowClientForm(true)}><Plus size={16}/>Создать клиента</button>
      </section>

      {showClientForm && <section className="card add-panel">
        <div className="panel-head">
          <h2>Создать клиента</h2>
          <button className="secondary" onClick={()=>setShowClientForm(false)}>Закрыть</button>
        </div>
        <div className="client-form-grid">
          <label>Имя клиента<input value={name} onChange={e=>setName(e.target.value)} placeholder="Например iPhone Evgeny" /></label>
          <label>Сервер<select value={clientServerId} onChange={e=>setClientServerId(e.target.value)}>
            {servers.map(server=><option key={server.id} value={server.id}>{server.name} · {server.ip}:{server.port}</option>)}
          </select></label>
        </div>
        <button onClick={()=>create().catch(handleError)}><Plus size={16}/>Создать и выдать config</button>
      </section>}

      {(selectedQr || selectedConfig) && <section className="card split">
        <div><div className="panel-head"><h2>Выданный конфиг</h2><button className="secondary" onClick={closeIssuedConfig}>Закрыть</button></div>{selectedConfig && <pre>{selectedConfig}</pre>}<button onClick={()=>downloadConfig(selectedConfig)}><Download size={16}/>Скачать .conf</button></div>
        {selectedQr && <img className="qr" src={selectedQr}/>}
      </section>}

      <section className="card">
        <table><thead><tr><th>Имя</th><th>Сервер</th><th>Статус</th><th>PublicKey</th><th>Allowed IPs</th><th></th></tr></thead><tbody>
          {clients.map(c=>{ const status = clientStatus(c.PublicKey); const config = clientConfigs[c.PublicKey]; return <tr key={c.PublicKey}>
            <td>{c.name||'—'}</td>
            <td>{activeServer?.name || '—'}</td>
            <td><span className={`badge ${status.className}`}>{status.label}</span></td>
            <td className="mono">{c.PublicKey}</td>
            <td>{c.AllowedIPs}</td>
            <td className="table-actions">
              <button className="secondary" onClick={()=>copyKey(c.PublicKey)}>Ключ</button>
              <button className="secondary" disabled={!config} onClick={()=>downloadConfig(config, `${c.name||'client'}.conf`)}><Download size={16}/></button>
              <button className="secondary" disabled={!config} onClick={()=>showQr(config).catch(handleError)}>QR</button>
              <button className="danger" onClick={()=>remove(c.PublicKey).catch(handleError)}><Trash2 size={16}/></button>
            </td>
          </tr> })}
        </tbody></table>
      </section>
    </>}

    {view==='orders' && <>
      <section className="card order-form">
        <input value={orderName} onChange={e=>setOrderName(e.target.value)} placeholder="Клиент или название заказа" />
        <input value={orderContact} onChange={e=>setOrderContact(e.target.value)} placeholder="Контакт: Telegram, телефон, email" />
        <select value={orderPlan} onChange={e=>setOrderPlan(e.target.value)}>
          <option>1 месяц</option><option>3 месяца</option><option>6 месяцев</option><option>12 месяцев</option>
        </select>
        <button onClick={addOrder}><Plus size={16}/>Добавить</button>
      </section>
      <section className="card">
        <h2>Заказы</h2>
        <table><thead><tr><th>Клиент</th><th>Контакт</th><th>Тариф</th><th>Статус</th><th></th></tr></thead><tbody>
          {orders.map(o=><tr key={o.id}><td>{o.name}<small>{o.created}</small></td><td>{o.contact||'—'}</td><td>{o.plan}</td><td><select value={o.status} onChange={e=>updateOrder(o.id,e.target.value)}><option>Новый</option><option>Оплачен</option><option>Выдан</option><option>Закрыт</option></select></td><td><button className="danger" onClick={()=>deleteOrder(o.id)}><Trash2 size={16}/></button></td></tr>)}
        </tbody></table>
      </section>
    </>}

    {view==='server' && <>
      <section className="section-head">
        <div><h2>Серверы</h2><p>Список подключений для будущего управления несколькими VPS</p></div>
        <button onClick={()=>setShowServerForm(true)}><Plus size={16}/>Добавить сервер</button>
      </section>
      {showServerForm && <section className="card add-panel">
        <div className="panel-head">
          <h2>{editingServerId?'Редактировать сервер':'Добавить сервер'}</h2>
          <button className="secondary" onClick={closeServerForm}>Закрыть</button>
        </div>
        <div className="server-form-grid">
          <label>Название<input value={serverName} onChange={e=>setServerName(e.target.value)} placeholder="Например VPS NL" /></label>
          <label>IP<input value={serverIp} onChange={e=>setServerIp(e.target.value)} placeholder="45.15.152.113" /></label>
          <label>Port<input value={serverPort} onChange={e=>setServerPort(e.target.value)} placeholder="47074" inputMode="numeric" /></label>
          <label>Token<input value={serverToken} onChange={e=>setServerToken(e.target.value)} placeholder="Token сервера" type="password" /></label>
        </div>
        <button onClick={addServer}><Plus size={16}/>Сохранить сервер</button>
      </section>}
      <section className="card">
        <table className="server-table"><thead><tr><th>Название</th><th>Endpoint</th><th>Token</th><th>Статус</th><th></th></tr></thead><tbody>
          {servers.map(s=><tr key={s.id} className={s.id===activeServerId?'selected-row':''}>
            <td><strong>{s.name}</strong>{s.id===activeServerId && <small>Активный сервер</small>}</td>
            <td className="mono">{s.ip || s.endpoint?.split(':')[0]}:{s.port || s.endpoint?.split(':')[1]}</td>
            <td>{s.token?<span className="badge ok">Задан</span>:<span className="badge muted">Не задан</span>}</td>
            <td>{serverConnection(s)?<span className="badge ok">Активен</span>:<span className="badge warn">Неактивен · редактировать</span>}</td>
            <td className="table-actions"><button className="secondary" onClick={()=>selectServer(s.id)}>Выбрать</button><button className="secondary" onClick={()=>editServer(s)}>Редактировать</button>{s.id!=='main' && <button className="danger" onClick={()=>deleteServer(s.id)}><Trash2 size={16}/></button>}</td>
          </tr>)}
        </tbody></table>
      </section>
      <section className="card"><h2>Активный сервер: awg dump</h2><pre>{dump||'Нет данных или awg недоступен из контейнера'}</pre></section>
    </>}
  </main>
}

createRoot(document.getElementById('root')).render(<App/>);
