import React, {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {RefreshCw, Trash2, Plus, Download} from 'lucide-react';
import './style.css';

const api = async (path, token, options={}) => {
  const res = await fetch(path, { ...options, headers: { 'Content-Type':'application/json', 'Authorization':`Bearer ${token}`, ...(options.headers||{}) }});
  if (!res.ok) throw new Error(await res.text());
  return res;
};

function App(){
  const [token,setToken]=useState(localStorage.getItem('token')||'');
  const [clients,setClients]=useState([]);
  const [dump,setDump]=useState('');
  const [name,setName]=useState('');
  const [lastConfig,setLastConfig]=useState('');
  const [qr,setQr]=useState('');
  const [error,setError]=useState('');

  const load=async()=>{
    setError('');
    localStorage.setItem('token',token);
    const r=await api('/api/clients',token);
    const j=await r.json();
    setClients(j.clients||[]); setDump(j.dump||'');
  };

  const create=async()=>{
    const r=await api('/api/clients',token,{method:'POST',body:JSON.stringify({name})});
    const j=await r.json(); setLastConfig(j.config); setName(''); await load();
    const qrRes=await api('/api/qrcode',token,{method:'POST',body:JSON.stringify({config:j.config})});
    setQr(URL.createObjectURL(await qrRes.blob()));
  };

  const remove=async(pk)=>{ if(!confirm('Удалить клиента?')) return; await api('/api/clients/'+encodeURIComponent(pk),token,{method:'DELETE'}); await load(); };
  const download=()=>{ const a=document.createElement('a'); a.href=URL.createObjectURL(new Blob([lastConfig],{type:'text/plain'})); a.download='amneziawg-client.conf'; a.click(); };

  useEffect(()=>{ if(token) load().catch(e=>setError(e.message)); },[]);

  return <main>
    <section className="hero">
      <div><h1>AmneziaWG Admin</h1><p>Управление клиентами существующего AWG-сервера</p></div>
      <button onClick={()=>load().catch(e=>setError(e.message))}><RefreshCw size={16}/>Обновить</button>
    </section>

    <section className="card">
      <label>Admin token</label>
      <input value={token} onChange={e=>setToken(e.target.value)} placeholder="ADMIN_TOKEN из .env" type="password" />
      {error && <pre className="error">{error}</pre>}
    </section>

    <section className="card row">
      <input value={name} onChange={e=>setName(e.target.value)} placeholder="Имя клиента, например iPhone Evgeny" />
      <button onClick={()=>create().catch(e=>setError(e.message))}><Plus size={16}/>Создать</button>
    </section>

    {lastConfig && <section className="card split">
      <div><h2>Новый конфиг</h2><pre>{lastConfig}</pre><button onClick={download}><Download size={16}/>Скачать .conf</button></div>
      {qr && <img className="qr" src={qr}/>} 
    </section>}

    <section className="card">
      <h2>Клиенты</h2>
      <table><thead><tr><th>Имя</th><th>PublicKey</th><th>Allowed IPs</th><th></th></tr></thead><tbody>
        {clients.map(c=><tr key={c.PublicKey}><td>{c.name||'—'}</td><td className="mono">{c.PublicKey}</td><td>{c.AllowedIPs}</td><td><button className="danger" onClick={()=>remove(c.PublicKey).catch(e=>setError(e.message))}><Trash2 size={16}/></button></td></tr>)}
      </tbody></table>
    </section>

    <section className="card"><h2>awg dump</h2><pre>{dump||'Нет данных или awg недоступен из контейнера'}</pre></section>
  </main>
}

createRoot(document.getElementById('root')).render(<App/>);
