from __future__ import annotations


RUC_SELECTORS = [
    'input[name="numRuc"]',
    'input[name="ruc"]',
    'input[name*="ruc" i]',
    'input[id*="ruc"]',
    'input[id*="num" i]',
    'input[placeholder*="RUC" i]',
    'input[aria-label*="RUC" i]',
    'input[type="text"]',
]

USER_SELECTORS = [
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
    'input[name="password"]',
    'input[name="clave"]',
    'input[name*="pass" i]',
    'input[id*="clave" i]',
    'input[id*="pass" i]',
    'input[type="password"]',
]

SUBMIT_SELECTORS = [
    'button[type="submit"]',
    'input[type="submit"]',
    'button:has-text("Iniciar sesi")',
    'button:has-text("Ingresar")',
    'button:has-text("Login")',
]
