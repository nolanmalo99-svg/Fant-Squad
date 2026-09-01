// ============================================
// FANT SQUAD — Grand Entrance Gate
// Shown once per session. Reads window.SITE_DATA (js/site-data.js)
// so it never needs hand-edited league facts.
// ============================================

function checkGate() {
  return sessionStorage.getItem('fantsquad_gate') === 'true';
}

function showGrandEntrance() {
  const data = window.SITE_DATA || {};
  const leagueName = data.league_name || 'Fant Squad';
  const teamCount = (data.standings || []).length || '—';
  const seasons = data.seasons_covered || [];
  const seasonCount = seasons.length || '—';
  const champs = data.champions_timeline || [];
  const uniqueChamps = new Set(champs.map(c => c.owner)).size;

  const champChips = champs.slice(-4).map((c, i, arr) => {
    const latest = i === arr.length - 1;
    const bg = latest ? 'rgba(255,255,255,0.12)' : 'rgba(255,255,255,0.05)';
    const border = latest ? '1px solid rgba(255,255,255,0.35)' : '1px solid rgba(255,255,255,0.12)';
    const fg = latest ? '#f5f7fa' : '#ffffff';
    return `<div style="background:${bg};border:${border};border-radius:3px;padding:0.45rem 0.65rem;text-align:center;min-width:86px;">
      <div style="font-size:0.5rem;color:#a7aebb;text-transform:uppercase;letter-spacing:1px;margin-bottom:0.15rem;">${c.season}</div>
      <div style="color:${fg};font-weight:800;font-size:0.82rem;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">🏆 ${(c.owner||'').split(' ')[0]}</div>
    </div>`;
  }).join('');

  const overlay = document.getElementById('gate-overlay');
  overlay.innerHTML = `
    <div style="min-height:100vh;display:flex;align-items:center;justify-content:center;background:#13151a;overflow:hidden;padding:1rem;position:relative;">
      <div style="position:absolute;inset:0;background-image:linear-gradient(rgba(255,255,255,0.03) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,0.03) 1px,transparent 1px);background-size:48px 48px;pointer-events:none;"></div>
      <div style="position:absolute;inset:0;background:radial-gradient(ellipse at 50% 65%,rgba(255,255,255,0.05) 0%,transparent 65%);pointer-events:none;"></div>

      <div style="text-align:center;position:relative;z-index:1;max-width:460px;width:100%;">
        <style>
          @keyframes pl-fadeUp   { from { opacity:0; transform:translateY(18px); } to { opacity:1; transform:translateY(0); } }
          @keyframes pl-fadeIn   { from { opacity:0; } to { opacity:1; } }
          @keyframes pl-lineGrow { from { width:0; } to { width:100%; } }
          @keyframes pl-statIn   { from { opacity:0; transform:translateY(10px); } to { opacity:1; transform:translateY(0); } }
          .gate-ball   { animation: pl-fadeIn  0.45s ease-out 0s    forwards; opacity:0; }
          .gate-eyebrow{ animation: pl-fadeUp  0.4s  ease-out 0.2s  forwards; opacity:0; }
          .gate-logo   { animation: pl-fadeUp  0.5s  ease-out 0.38s forwards; opacity:0; }
          .gate-sub    { animation: pl-fadeUp  0.4s  ease-out 0.6s  forwards; opacity:0; }
          .gate-divider{ animation: pl-lineGrow 0.55s ease-out 0.75s forwards; }
          .gate-s1     { animation: pl-statIn  0.35s ease-out 0.95s forwards; opacity:0; }
          .gate-s2     { animation: pl-statIn  0.35s ease-out 1.1s  forwards; opacity:0; }
          .gate-s3     { animation: pl-statIn  0.35s ease-out 1.25s forwards; opacity:0; }
          .gate-champs { animation: pl-fadeUp  0.45s ease-out 1.55s forwards; opacity:0; }
          .gate-btn    { animation: pl-fadeUp  0.4s  ease-out 2.0s  forwards; opacity:0; }
          .gate-footer { animation: pl-fadeIn  0.4s  ease-out 2.5s  forwards; opacity:0; }
          .enter-btn { padding: 0.8rem 2.8rem; background: #f5f7fa; color: #13151a; border: none;
            border-radius: 4px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            font-size: 0.8rem; font-weight: 800; text-transform: uppercase; letter-spacing: 2px;
            cursor: pointer; transition: all 0.18s ease; }
          .enter-btn:hover { background: #ffffff; transform: translateY(-1px); box-shadow: 0 6px 22px rgba(255,255,255,0.18); }
        </style>

        <div class="gate-ball" style="font-size:3rem;margin-bottom:0.75rem;display:block;line-height:1;">🏈</div>
        <div class="gate-eyebrow" style="margin-bottom:0.4rem;">
          <span style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;font-size:0.6rem;color:#3E8ED9;letter-spacing:3px;text-transform:uppercase;font-weight:800;">Fantasy Football</span>
        </div>
        <div class="gate-logo" style="margin-bottom:0.15rem;">
          <h1 style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;font-size:clamp(1.9rem,7.5vw,3.4rem);font-weight:900;color:#ffffff;letter-spacing:-0.5px;text-transform:uppercase;line-height:1.05;overflow-wrap:break-word;word-break:break-word;max-width:100%;">${leagueName}</h1>
        </div>
        <div class="gate-sub" style="margin-bottom:1.4rem;">
          <p style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#c8c8c8;font-size:0.72rem;letter-spacing:2.5px;text-transform:uppercase;">League</p>
        </div>
        <div style="overflow:hidden;max-width:180px;margin:0 auto 1.5rem;height:2px;">
          <div class="gate-divider" style="height:2px;background:linear-gradient(90deg,transparent,#ffffff,transparent);width:0;"></div>
        </div>

        <div style="display:flex;justify-content:center;gap:2.25rem;flex-wrap:wrap;margin-bottom:1.75rem;">
          <div class="gate-s1" style="text-align:center;">
            <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;font-size:1.9rem;font-weight:900;color:#ffffff;line-height:1;">${teamCount}</div>
            <div style="font-size:0.58rem;color:#a7aebb;text-transform:uppercase;letter-spacing:1.5px;margin-top:0.2rem;">Teams</div>
          </div>
          <div class="gate-s2" style="text-align:center;">
            <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;font-size:1.9rem;font-weight:900;color:#ffffff;line-height:1;">${seasonCount}</div>
            <div style="font-size:0.58rem;color:#a7aebb;text-transform:uppercase;letter-spacing:1.5px;margin-top:0.2rem;">Seasons</div>
          </div>
          <div class="gate-s3" style="text-align:center;">
            <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;font-size:1.9rem;font-weight:900;color:#ffffff;line-height:1;">${uniqueChamps || '—'}</div>
            <div style="font-size:0.58rem;color:#a7aebb;text-transform:uppercase;letter-spacing:1.5px;margin-top:0.2rem;">Champions</div>
          </div>
        </div>

        ${champChips ? `<div class="gate-champs" style="margin-bottom:2rem;">
          <div style="display:flex;justify-content:center;gap:0.4rem;flex-wrap:wrap;margin-bottom:0.65rem;">${champChips}</div>
        </div>` : '<div class="gate-champs" style="margin-bottom:2rem;"></div>'}

        <div class="gate-btn" style="margin-bottom:1.4rem;">
          <button class="enter-btn" onclick="dismissEntrance()">Enter the League</button>
        </div>

        <div class="gate-footer">
          <p style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#b0b0b0;font-size:0.6rem;letter-spacing:2px;text-transform:uppercase;">Draft Smart &bull; Score Big &bull; Take the Belt</p>
        </div>
      </div>
    </div>
  `;
}

function dismissEntrance() {
  sessionStorage.setItem('fantsquad_gate', 'true');
  var overlay = document.getElementById('gate-overlay');
  overlay.style.transition = 'opacity 0.45s ease';
  overlay.style.opacity = '0';
  setTimeout(function() {
    overlay.remove();
    document.body.style.overflow = '';
  }, 450);
}

if (!checkGate()) {
  document.addEventListener('DOMContentLoaded', function() {
    var overlay = document.createElement('div');
    overlay.id = 'gate-overlay';
    overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;z-index:9999;';
    document.body.prepend(overlay);
    document.body.style.overflow = 'hidden';
    showGrandEntrance();
  });
}
