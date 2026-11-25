/* v128: confere /versao.json a cada 3 min. Se a versão mudou: mostra faixa e recarrega sozinho quando não há edição aberta. */
(function () {
  var atual = (document.currentScript && document.currentScript.getAttribute('data-versao')) || null;
  if (!atual) return;
  function editando() {
    var a = document.activeElement;
    if (a && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName) && a.type !== 'button' && a.type !== 'submit') return true;
    var forms = document.querySelectorAll('form');
    for (var i = 0; i < forms.length; i++) {
      var els = forms[i].querySelectorAll('input[type=text],input[type=email],input[type=password],input[type=number],input[type=tel],textarea');
      for (var j = 0; j < els.length; j++) if (els[j].value !== els[j].defaultValue) return true;
    }
    return !!document.querySelector('.modal.aberto,.modal.open,dialog[open]');
  }
  function faixa() {
    if (document.getElementById('faixa-versao')) return;
    var d = document.createElement('div'); d.id = 'faixa-versao';
    d.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:99999;background:#0B3A57;color:#fff;padding:10px 14px;font:600 14px Arial;text-align:center';
    d.innerHTML = 'Há uma versão nova do sistema. <button style="margin-left:8px;padding:6px 12px;border:0;border-radius:8px;background:#0EA5A0;color:#fff;font-weight:700;cursor:pointer" onclick="location.reload()">Atualizar agora</button>';
    document.body.appendChild(d);
  }
  function conferir() {
    fetch('/versao.json', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (j) {
      if (j && j.versao && j.versao !== atual) { if (editando()) faixa(); else location.reload(); }
    }).catch(function () {});
  }
  setInterval(conferir, window.LIFEMAX_VERSAO_INTERVALO_MS || 180000);
})();
