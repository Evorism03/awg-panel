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

function App(){
  const [view,setView]=useState('home');
  const [username,setUsername]=useState('admin');
  const [password,setPassword]=useState('');
  const [isLoggedIn,setIsLoggedIn]=useState(false);
  const [clients,setClients]=useState([]);
  const [dump,setDump]=useState('');
  const [name,setName]=useState('');
  const [orderName,setOrderName]=useState('');
  const [orderContact,setOrderContact]=useState('');
  const [orderPlan,setOrderPlan]=useState('1 месяц');
  const [orders,setOrders]=useState(()=>JSON.parse(localStorage.getItem('orders')||'[]'));
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

  const load=async()=>{
    setError('');
    const r=await api('/api/clients');
    const j=await r.json();
    setClients(j.clients||[]); setDump(j.dump||'');
    setIsLoggedIn(true);
  };

  const login=async()=>{
    setError('');
    await api('/api/login',{method:'POST',body:JSON.stringify({username:username.trim(),password})});
    setPassword('');
    await load();
  };

  const create=async()=>{
    const r=await api('/api/clients',{method:'POST',body:JSON.stringify({name})});
    const j=await r.json(); setLastConfig(j.config); setName(''); await load();
    const qrRes=await api('/api/qrcode',{method:'POST',body:JSON.stringify({config:j.config})});
    setQr(URL.createObjectURL(await qrRes.blob()));
  };

  const remove=async(pk)=>{ if(!confirm('Удалить клиента?')) return; await api('/api/clients/'+encodeURIComponent(pk),{method:'DELETE'}); await load(); };
  const download=()=>{ const a=document.createElement('a'); a.href=URL.createObjectURL(new Blob([lastConfig],{type:'text/plain'})); a.download='amneziawg-client.conf'; a.click(); };
  const logout=async()=>{ await api('/api/logout',{method:'POST'}).catch(()=>{}); setIsLoggedIn(false); setClients([]); setDump(''); setError(''); };
  const saveOrders=(next)=>{ setOrders(next); localStorage.setItem('orders',JSON.stringify(next)); };
  const addOrder=()=>{
    const title = orderName.trim();
    if(!title) return;
    saveOrders([{id:crypto.randomUUID(), name:title, contact:orderContact.trim(), plan:orderPlan, status:'Новый', created:new Date().toLocaleString('ru-RU')}, ...orders]);
    setOrderName(''); setOrderContact('');
  };
  const updateOrder=(id,status)=>saveOrders(orders.map(o=>o.id===id?{...o,status}:o));
  const deleteOrder=(id)=>saveOrders(orders.filter(o=>o.id!==id));

  useEffect(()=>{ load().catch(()=>setIsLoggedIn(false)); },[]);

  const nav = [
    ['home','Главная',Home],
    ['clients','Клиенты',Users],
    ['orders','Заказы',ShoppingCart],
    ['server','Сервер',Server],
  ];
  const authed = isLoggedIn;

  return <main>
    <header className="topbar">
      <div><h1>AmneziaWG Admin</h1><p>Панель управления сервером, клиентами и заказами</p></div>
      <button onClick={()=>load().catch(handleError)}><RefreshCw size={16}/>Обновить</button>
    </header>

    <nav className="menu">
      {nav.map(([id,label,Icon])=><button key={id} className={view===id?'active secondary':'secondary'} onClick={()=>setView(id)}><Icon size={17}/>{label}</button>)}
    </nav>

    <section className="card">
      <label>Авторизация</label>
      <div className="token-row">
        <input value={username} onChange={e=>setUsername(e.target.value)} placeholder="Логин" autoComplete="username" />
        <input value={password} onChange={e=>setPassword(e.target.value)} onKeyDown={e=>{ if(e.key==='Enter') login().catch(handleError); }} placeholder="Пароль" type="password" autoComplete="current-password" />
        <button onClick={()=>login().catch(handleError)}><RefreshCw size={16}/>Войти</button>
        <button className="secondary" onClick={logout}><LogOut size={16}/>Выйти</button>
      </div>
      {error && <pre className="error">{error}</pre>}
    </section>

    {view==='home' && <section className="grid">
      <div className="card metric"><Users size={22}/><span>Клиенты</span><strong>{clients.length}</strong></div>
      <div className="card metric"><ShoppingCart size={22}/><span>Заказы</span><strong>{orders.length}</strong></div>
      <div className="card metric"><Activity size={22}/><span>API</span><strong>{authed?'OK':'Login'}</strong></div>
    </section>}

    {view==='clients' && <>
      <section className="card row">
        <input value={name} onChange={e=>setName(e.target.value)} placeholder="Имя клиента, например iPhone Evgeny" />
        <button onClick={()=>create().catch(handleError)}><Plus size={16}/>Создать</button>
      </section>

      {lastConfig && <section className="card split">
        <div><h2>Новый конфиг</h2><pre>{lastConfig}</pre><button onClick={download}><Download size={16}/>Скачать .conf</button></div>
        {qr && <img className="qr" src={qr}/>} 
      </section>}

      <section className="card">
        <h2>Клиенты</h2>
        <table><thead><tr><th>Имя</th><th>PublicKey</th><th>Allowed IPs</th><th></th></tr></thead><tbody>
          {clients.map(c=><tr key={c.PublicKey}><td>{c.name||'—'}</td><td className="mono">{c.PublicKey}</td><td>{c.AllowedIPs}</td><td><button className="danger" onClick={()=>remove(c.PublicKey).catch(handleError)}><Trash2 size={16}/></button></td></tr>)}
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
      <section className="card">
        <h2>Сервер</h2>
        <div className="server-line"><span>Endpoint</span><strong>45.15.152.113:47074</strong></div>
        <div className="server-line"><span>Интерфейс</span><strong>awg0</strong></div>
        <div className="server-line"><span>Статус API</span><strong>{authed?'Подключен':'Нужен вход'}</strong></div>
      </section>
      <section className="card"><h2>awg dump</h2><pre>{dump||'Нет данных или awg недоступен из контейнера'}</pre></section>
    </>}
  </main>
}

createRoot(document.getElementById('root')).render(<App/>);
