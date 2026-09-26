// Atualiza a prévia das parcelas enquanto a condição de pagamento é digitada.
document.addEventListener("DOMContentLoaded", function () {
  var previa = document.getElementById("previa-condicao");
  var condicao = document.getElementById("id_condicao_pagamento");
  if (!previa || !condicao) return;  // pedido já aprovado: só leitura
  var primeiro = document.getElementById("id_primeiro_vencimento");
  var entrega = document.getElementById("id_previsao_entrega");
  var espera;

  function atualizar() {
    var params = new URLSearchParams({
      condicao: condicao.value,
      primeiro: primeiro ? primeiro.value : "",
      base: entrega ? entrega.value : "",
    });
    fetch(previa.dataset.url + "?" + params.toString(), { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (dados) {
        previa.textContent = dados.texto;
        previa.style.color = dados.ok ? "" : "#ba2121";
        previa.style.fontWeight = dados.ok ? "" : "bold";
      })
      .catch(function () {});
  }

  function agendar() {
    clearTimeout(espera);
    espera = setTimeout(atualizar, 250);
  }

  [condicao, primeiro, entrega].forEach(function (campo) {
    if (!campo) return;
    campo.addEventListener("input", agendar);
    campo.addEventListener("change", agendar);
  });

  // O calendário do painel preenche as datas sem disparar eventos; confere a cada segundo.
  function valores() {
    return [condicao, primeiro, entrega].map(function (c) { return c ? c.value : ""; }).join("|");
  }
  var ultimo = valores();
  setInterval(function () {
    var agora = valores();
    if (agora !== ultimo) { ultimo = agora; agendar(); }
  }, 1000);
});
