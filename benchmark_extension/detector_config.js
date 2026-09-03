"use strict";

// Configuração declarativa. Este arquivo pode ser refinado após o piloto sem
// alterar o coletor. Os nomes são comparados após lowercase, remoção de acentos
// e normalização de espaços.
globalThis.SUBNEXUS_BENCHMARK_DETECTORS = Object.freeze({
  contentIdPattern: /^[a-zA-Z0-9][a-zA-Z0-9_-]{5,127}$/,
  actions: Object.freeze([
    Object.freeze({
      action: "validate_media",
      exact: Object.freeze(["validate media"]),
    }),
    Object.freeze({
      action: "approve",
      exact: Object.freeze(["approve", "aprovar"]),
    }),
    Object.freeze({
      action: "validate",
      exact: Object.freeze(["validate", "validar"]),
    }),
    Object.freeze({
      action: "download",
      exact: Object.freeze([
        "download subtitle",
        "download legenda",
        "baixar legenda",
        "download",
      ]),
    }),
    Object.freeze({
      action: "upload_open",
      exact: Object.freeze([
        "upload subtitle",
        "upload legenda",
        "enviar legenda",
      ]),
    }),
    Object.freeze({
      action: "edit",
      exact: Object.freeze(["edit", "editar"]),
    }),
    Object.freeze({
      action: "play",
      exact: Object.freeze(["play", "reproduzir"]),
    }),
  ]),
  successWords: Object.freeze([
    "success",
    "successful",
    "successfully",
    "sucesso",
    "concluido",
    "completed",
    "uploaded",
    "enviado",
    "approved",
    "aprovado",
    "validated",
    "validado",
  ]),
  failureWords: Object.freeze([
    "error",
    "erro",
    "failed",
    "failure",
    "falhou",
    "invalid",
    "invalido",
    "rejected",
    "rejeitado",
  ]),
  notificationSelector: [
    "[role='alert']",
    "[role='status']",
    "[aria-live]",
    "[class*='toast' i]",
    "[class*='snackbar' i]",
    "[class*='notification' i]",
  ].join(","),
  interactiveSelector: [
    "button",
    "a",
    "input[type='button']",
    "input[type='submit']",
    "input[type='radio']",
    "[role='button']",
    "[role='menuitem']",
    "[role='option']",
    "[role='radio']",
  ].join(","),
  languageWords: Object.freeze([
    "portuguese",
    "portugues",
    "portuguese brazil",
    "spanish",
    "espanol",
    "english",
    "ingles",
  ]),
});
