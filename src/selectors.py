from __future__ import annotations


RUC_SELECTORS = [
    '#txtRuc',
    'input[id="txtRuc"]',
    'input[name="numRuc"]',
    'input[name="ruc"]',
    'input[name*="ruc" i]',
    'input[id*="ruc"]',
    'input[placeholder*="RUC" i]',
    'input[aria-label*="RUC" i]',
    'input[type="text"]',
]

USER_SELECTORS = [
    '#txtUsuario',
    'input[id="txtUsuario"]',
    'input[name="codUsuario"]',
    'input[name="usuario"]',
    'input[name*="user" i]',
    'input[name*="usu" i]',
    'input[id*="usuario"]',
    'input[id*="user" i]',
    'input[placeholder*="usuario" i]',
    'input[placeholder*="user" i]',
    'input[aria-label*="usuario" i]',
    'input[autocomplete="username"]',
    'input[type="text"]',
]

PASSWORD_SELECTORS = [
    '#txtContrasena',
    'input[id="txtContrasena"]',
    'input[name="password"]',
    'input[name="clave"]',
    'input[name*="pass" i]',
    'input[id*="clave" i]',
    'input[id*="pass" i]',
    'input[type="password"]',
]

SUBMIT_SELECTORS = [
    '#btnAceptar',
    '#btnIngresar',
    'button[id*="ingresar" i]',
    'button[id*="aceptar" i]',
    'button[type="submit"]',
    'input[type="submit"]',
    'button:has-text("Iniciar sesi")',
    'button:has-text("Ingresar")',
    'button:has-text("Login")',
]
