# Guía de uso — CodeReviewX

Guía práctica para **trabajar con los reviews** que genera el bot: cómo se dispara, cómo leer cada hallazgo, cómo clasificarlo para decidir qué hacer y cómo responder. No es la guía de instalación (eso está en `README.md` / `SETUP.md`), sino la de uso del día a día.

---

## 1. Qué hace el bot, en una frase

Cada vez que abres o actualizas un Pull Request, el bot lee el diff, lo pasa por análisis estático (Ruff / ESLint) y por Claude, y publica **un review con comentarios en las líneas exactas** donde detecta posibles problemas. No aprueba ni rechaza el PR: solo comenta (`COMMENT`). La decisión final siempre es tuya.

---

## 2. Cómo se usa el sistema

No tienes que ejecutar nada. El flujo es automático:

1. Abres un PR (o haces un push nuevo a uno ya abierto) en un repo donde la App esté instalada.
2. En **segundos a ~1 minuto** aparece el review de `codereviewpersonalapp[bot]`.
3. Lees los comentarios, decides cuáles aplicar y haces los cambios en un commit nuevo.
4. Al pushear ese commit, el bot **vuelve a revisar** desde cero (genera un review nuevo, no edita el anterior).

### Cuándo actúa y cuándo no

| Situación | ¿Revisa? |
|---|---|
| PR `opened` o nuevo push (`synchronize`) | ✅ Sí |
| Archivos `.py`, `.js`, `.ts`, `.jsx`, `.tsx` | ✅ Sí |
| PR solo con `.md`, `.json`, `.css`, imágenes, etc. | ❌ No (no publica nada) |
| Líneas **eliminadas** o sin cambios | ❌ No (solo mira líneas **añadidas**, las `+` del diff) |
| Archivo eliminado | ❌ No |

### Límites que conviene conocer

- **Máximo 5 comentarios por archivo.** En un archivo muy problemático puede haber más cosas de las que reporta.
- **Solo ve el diff, no el archivo completo ni el resto del repo.** No conoce el contexto de funciones que no cambiaste, ni tu configuración, ni tu CSS.
- **Cada push = review nuevo.** No mantiene conversación ni recuerda lo que ya comentó.

---

## 3. Anatomía de un comentario

Cada comentario inline tiene esta forma:

```
🤖 Code Review IA

<explicación del posible problema en la línea señalada>
```

Y el review trae un resumen arriba:

```
🔍 Revisión automática completada
Se encontraron 4 observaciones en 3 archivo(s).
```

Léelo como lo que es: **observaciones de un revisor cauteloso**, no una lista de errores confirmados. El bot prefiere avisar de más. Tu trabajo es filtrar.

---

## 4. Clasificar los hallazgos (lo más importante)

Antes de tocar código, **triá cada comentario** en uno de estos cuatro niveles. La señal más útil está en el *lenguaje* que usa el bot: si afirma ("esto concatena `id` sin sanitizar") suele ser real; si condiciona ("si… podría… en el futuro…") suele ser preventivo.

### 🔴 Crítico — arréglalo antes de mergear
Bugs reales o fallos de seguridad con impacto directo. El bot lo describe en presente y sin condicionales.

- Inyección SQL / comandos / HTML por concatenar entrada sin sanitizar.
- Secretos o credenciales en el código.
- Null/undefined que reventará en ejecución (`data.x.y` sin verificar `data.x`).
- Excepciones no capturadas en rutas que sí se ejecutan (`JSON.parse` de entrada externa sin `try/catch`).

> Ejemplo real (PR de prueba): *"Inyección SQL: el parámetro `id` se concatena directamente en la query"* → **crítico, se arregla**.

### 🟠 Importante — verifícalo, probablemente toca cambio
Problemas plausibles que dependen de contexto que el bot no ve. Aquí **no apliques a ciegas**: confirma en tu código y, si tiene razón, corrige.

- Race conditions, estado compartido, async mal usado.
- Validación de entrada ausente en un endpoint.
- Lógica que parece contradecir la intención del cambio.

> Ejemplo real (PR #16): *"el `?` y el `jotai-spark` se renderizan en la misma posición; si el CSS no oculta uno, se solaparán"* → **verifica tu CSS**; si ya lo controla, ciérralo.

### 🟡 Opcional / mejora — a tu criterio
Sugerencias de robustez o rendimiento que no rompen nada hoy.

- Refactors defensivos ("este patrón es frágil para el futuro").
- Micro-optimizaciones (p. ej. peticiones secuenciales que podrían ir en paralelo).

> Ejemplo real (PR #16): *"usar `innerHTML` para el contenedor es frágil aunque hoy usas `textContent`"* → mejora, no urgente.

### ⚪ Ruido / no aplica — ignóralo
Técnicamente correcto pero irrelevante para tu proyecto, o un falso positivo por falta de contexto.

- Compatibilidad con navegadores muertos (IE11).
- Riesgos basados en supuestos que no se dan en tu código.

> Ejemplos reales (PR #16): *"`non-scaling-stroke` no funciona en IE11"* (no das soporte a IE11) y *"la clase `is-peeking` podría quedar de una sesión anterior"* (las clases del DOM no sobreviven a una recarga) → **ignóralos**.

### Tabla rápida de decisión

| Nivel | Cómo lo reconoces | Acción |
|---|---|---|
| 🔴 Crítico | Afirma un bug/seguridad real, en presente | Arreglar antes de mergear |
| 🟠 Importante | "Si… / depende de…" sobre algo plausible | Verificar en tu código, corregir si aplica |
| 🟡 Opcional | "Frágil / mejor / podría optimizarse" | Aplicar si vale la pena |
| ⚪ Ruido | Correcto pero fuera de tu contexto, o supuesto falso | Ignorar |

---

## 5. Cómo responder y aplicar cambios

El bot deja sus comentarios como un review normal de GitHub, así que respondes igual que a un humano.

### Aplicar un cambio
1. Corrige en tu rama local.
2. `git commit` + `git push` a la **misma rama** del PR.
3. El bot vuelve a revisar automáticamente; si arreglaste el problema, ya no reaparecerá.

### Responder en el hilo (recomendado para dejar traza)
En cada comentario tienes **Reply**. Úsalo para documentar tu decisión, sobre todo cuando **no** vas a aplicar el cambio:

- Si lo arreglas: *"Hecho en `<sha>`."*
- Si no aplica: *"No aplica: no damos soporte a IE11."* / *"Falso positivo: el CSS ya oculta uno de los dos estados."*
- Si lo dejas para después: *"Válido, lo dejo como deuda técnica en #<issue>."*

> El bot no responde a tus replies (cada push es un review nuevo), pero la traza queda para ti y para cualquiera que revise el PR.

### Cerrar / resolver
Marca el hilo como **Resolved** cuando lo hayas atendido o descartado, para mantener limpia la conversación.

### Flujo recomendado de principio a fin
1. Lee el resumen y los comentarios.
2. Clasifica cada uno (🔴/🟠/🟡/⚪) — sección 4.
3. Arregla los 🔴 y los 🟠 confirmados en un commit.
4. Responde y resuelve los que ignoras (⚪) o pospones, explicando por qué.
5. Pushea → deja que el bot revise de nuevo → mergea cuando estés conforme.

---

## 6. Cómo te ayuda (y cómo sacarle provecho)

- **Segunda mirada inmediata**, sin esperar a un revisor humano: detecta inyecciones, null refs, validaciones ausentes y lógica confusa en el momento de abrir el PR.
- **Te enseña a revisar**: clasificar sus hallazgos entrena tu propio criterio sobre seguridad y bugs.
- **PRs más pequeños = mejores reviews.** Como solo ve el diff y corta a 5 comentarios por archivo, un PR enfocado obtiene una revisión más completa y útil que uno gigante.
- **No sustituye al juicio humano ni a los tests.** Es un complemento: confírmalo siempre contra tu código y tu suite de pruebas.

---

## 7. Si el bot no comenta

1. ¿El PR toca archivos de código soportados (`.py/.js/.ts/.jsx/.tsx`)? Si es solo docs/config, no publica ningún review.
2. ¿El evento fue `opened`/`synchronize`? Reabrir un PR viejo no lo redispara; haz un push nuevo.
3. Si aun así no aparece, el fallo está en el servidor (Railway): revisa los logs del deploy. Los errores del pipeline se registran ahí.
