# Voz — Dictado por voz local con Whisper

Voz es una herramienta de dictado por voz que ejecuta **Whisper** localmente mediante `faster-whisper`. Sin conexión a internet, sin enviar audio a ningún servidor.

## ⚡ Cómo funciona

1. **Abrís Voz** → la primera vez se abre Configuración para elegir idioma y micrófono
2. Ponés el cursor donde querés el texto (un chat, un documento, un correo…)
3. **F10** para empezar a grabar → suena un pitido agudo
4. Hablás. **F10** otra vez para detener → suena un pitido grave
5. Whisper transcribe y el texto **se pega solo donde está el cursor** → suena un pitido doble
6. El texto queda además en el **portapapeles** y guardado en `data/dictations/`

F10 funciona aunque la ventana esté minimizada. Cerrar la ventana cierra el programa por completo.

Mientras transcribe, F10 se ignora (pitido de error): esperá al pitido doble para volver a grabar.

## 📦 Requisitos

- **Windows 10/11** (no testeado en otras plataformas)
- **4 GB RAM mínimo** (8 GB recomendado)
- **Micrófono** (cualquier dispositivo de entrada de audio)
- ~**1.5 GB de espacio** para el modelo Whisper (descarga única)

## 🚀 Instalación

El repositorio no incluye el ejecutable. Hay dos formas de usar Voz:

```powershell
# 1) Directo con Python
pip install -r requirements.txt
python main.py
```

```powershell
# 2) Compilar el .exe (queda en dist\voz\voz.exe)
pip install -r requirements.txt
.\build.ps1
```

Para compartirlo, comprimí la carpeta `dist\voz\` (sin `models\`, `data\` ni `config.json`): quien la reciba ejecuta `voz.exe` y el modelo se descarga solo la primera vez.

## 🎮 Atajos y uso

| Tecla/Acción | Descripción |
|---|---|
| **F10** | Iniciar/detener grabación (funciona en segundo plano) |
| **Botón Copiar** | Copia todo el texto de la ventana, **incluidas tus correcciones** |
| **Botón Limpiar** | Borra el texto acumulado |
| **Botón Guardar como...** | Guarda el texto de la ventana en un `.txt` |
| **Botón Configurar** | Idioma, micrófono, tecla rápida, pegado automático, sonidos |

El área de texto solo contiene lo dictado y se puede editar libremente. El estado (grabando, transcribiendo, errores) se muestra en la barra inferior; el detalle técnico va a `data/voz.log`.

### Opciones (`config.json`)

Se crea solo al guardar la Configuración. Las que no aparecen en la ventana se cambian a mano:

| Clave | Por defecto | Qué hace |
|---|---|---|
| `language` | `"es"` | Idioma del dictado (`"auto"` para detectarlo) |
| `hotkey` | `"F10"` | Tecla global (F1–F24, Insert, Pause, teclas multimedia…) |
| `microphone_device` | `null` | `null` = el micrófono por defecto de Windows |
| `auto_copy` | `true` | Copiar al portapapeles al terminar |
| `auto_paste` | `true` | Pegar (Ctrl+V) donde esté el cursor al terminar |
| `auto_save` | `true` | Guardar cada dictado en `data/dictations/` |
| `sounds` | `true` | Pitidos de inicio, fin, listo y error |
| `model` | `"turbo"` | Modelo Whisper |
| `model_unload_min` | `10` | Minutos sin uso para liberar el modelo de la RAM (`0` = nunca) |
| `batch_size` | `8` | Trozos de audio transcritos a la vez (`0` = modo clásico, más lento) |
| `device` / `compute_type` | `"cpu"` / `"int8"` | Dispositivo y precisión de cálculo |

## 🏗️ Arquitectura

```
voz/
├── main.py                  ← Entry point
├── core/                    ← Capa pura (sin GUI)
│   ├── config.py            ← Configuración central (config.json)
│   ├── recorder.py          ← Captura de micrófono (sounddevice)
│   ├── audio.py             ← Resampleo a 16 kHz
│   ├── transcriber.py       ← Transcripción (faster-whisper)
│   ├── clipboard.py         ← Copiar (pyperclip) y pegar (Ctrl+V simulado)
│   ├── sounds.py            ← Pitidos de aviso
│   ├── storage.py           ← Persistencia (JSON + TXT)
│   └── models.py            ← Dataclasses (TranscriptionResult, Segment)
├── gui/                     ← Capa de interfaz (Tkinter)
│   ├── dictation_app.py     ← Ventana principal + máquina de estados
│   ├── settings_window.py   ← Ventana de configuración
│   └── hotkey_listener.py   ← Tecla global (pynput)
├── tests/                   ← Tests unitarios y de integración (pytest)
├── data/
│   ├── dictations/          ← Transcripciones guardadas (.json + .txt)
│   └── voz.log              ← Log de la última sesión
└── dist/
    └── voz/
        ├── voz.exe              ← Aplicación compilada
        └── models/whisper/      ← Modelo Whisper (copia única)
```

> 💡 Existe **un solo modelo en todo el proyecto**: `dist/voz/models/whisper/`.
> El `.exe` y `main.py` (modo script) apuntan ambos a esa misma carpeta,
> así no importa cómo inicies la app — la descarga ocurre exactamente una vez.

### Principios

| Principio | Descripción |
|---|---|
| **Separación de capas** | `core/` = lógica pura (no sabe de GUI), `gui/` = interfaz |
| **Máquina de estados** | `idle → recording → transcribing → done → idle` (más `error`) |
| **Un solo hilo toca la interfaz** | Los hilos de fondo (tecla global, transcripción, carga del modelo) entregan su resultado con `_post()` a una cola que el hilo de Tk vacía cada 25 ms |
| **Precarga del modelo** | Whisper se carga en segundo plano al iniciar |
| **Descarga en reposo** | Tras `model_unload_min` minutos sin uso el modelo se libera de la RAM (~1.5 GB). Se recarga solo **al empezar a grabar**, mientras hablás, así que no añade espera |
| **Transcripción por lotes** | El audio se corta en los silencios y se transcriben varios trozos a la vez (`batch_size`) |

## 🧠 Tecnologías

| Componente | Librería | Propósito |
|---|---|---|
| **Modelo ASR** | [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) | Transcripción local con CTranslate2 |
| **Modelo** | `mobiuslabsgmbh/faster-whisper-large-v3-turbo` | Whisper turbo |
| **Audio input** | [`sounddevice`](https://python-sounddevice.readthedocs.io/) | Captura de micrófono (PortAudio) |
| **Resampleo** | `scipy.signal.resample_poly` | De la frecuencia del micrófono a 16 kHz |
| **GUI** | [`Tkinter`](https://docs.python.org/3/library/tkinter.html) | Interfaz gráfica |
| **Tecla global y pegado** | [`pynput`](https://pynput.readthedocs.io/) | F10 global y Ctrl+V simulado |
| **Clipboard** | [`pyperclip`](https://pyperclip.readthedocs.io/) | Copia al portapapeles |
| **Sonidos** | `winsound` (estándar) | Pitidos de aviso |
| **Build** | [`PyInstaller`](https://pyinstaller.org/) | Empaquetado en `.exe` single-folder |

## 📐 Decisiones técnicas

### ¿Por qué `--onedir` y no `--onefile`?

El modelo Whisper pesa ~1.5 GB. PyInstaller no puede empaquetar eso dentro de un solo `.exe`
de forma práctica. El modelo se guarda en `dist/voz/models/whisper/` junto al ejecutable
para que toda la app viva en una sola carpeta autocontenida.

### ¿Por qué Turbo y no Small/Base?

Whisper **turbo** ofrece la mejor relación calidad/velocidad en español.

### ¿Por qué transcripción por lotes con `without_timestamps=False`?

El modo por lotes de `faster-whisper` es casi el doble de rápido en dictados largos, pero con
su valor por defecto (`without_timestamps=True`) devolvía trozos enteros de 30 s en minúsculas
y sin puntuación. Con `False` el texto sale igual que en el modo clásico, a la misma velocidad.

### ¿Por qué F10 se ignora mientras transcribe?

Antes la pulsación quedaba "en cola" y la grabación arrancaba sola al terminar la
transcripción, quizá minutos después y sin que nadie lo notara. Ahora suena un pitido de
error y no pasa nada más.

### ¿Por qué el pegado automático no pega dentro de Voz?

Si la ventana de Voz tiene el foco, el texto ya se está añadiendo a su área de texto;
un Ctrl+V lo duplicaría. En ese caso solo se copia.

### ¿Por qué no hay system tray?

Se eliminó intencionalmente para simplificar. Cerrar ventana = cerrar programa.

### ¿Por qué `sample_rate` y `channels` no son configurables?

Whisper solo acepta audio mono a 16 kHz. Voz detecta la frecuencia nativa del micrófono
(44100 Hz, 48000 Hz…) y la convierte sola.

## ⚡ Rendimiento

Equipo de prueba: **Beelink Ryzen 7 7840HS (8 núcleos), 32 GB RAM, Windows 11**, CPU, modelo turbo `int8`.
Medido con una voz sintética; con voz real los tiempos pueden variar.

| Audio | Modo clásico, 4 hilos (antes) | Por lotes, 8 hilos (ahora) |
|---|---|---|
| 84 s | ~22 s | ~13 s |
| 4 min 15 s | ~65 s | ~34 s |

| Métrica | Valor |
|---|---|
| **RAM en uso** | ~1.2–1.5 GB con el modelo cargado |
| **Carga del modelo** | 2–10 s desde disco (la primera vez, además, la descarga de ~1.5 GB) |
| **Temperatura CPU** | ~75–80 °C durante transcripciones largas |

## 🐛 Solución de problemas

| Problema | Causa | Solución |
|---|---|---|
| El texto no se pega solo | La app de destino corre como Administrador, o Voz tenía el foco | El texto está en el portapapeles: Ctrl+V manual. O ejecutar Voz como Administrador |
| Se pega en la ventana equivocada | El pegado va a la ventana que tenga el foco **al terminar** | Dejá el cursor en el destino hasta oír el pitido doble, o desactivá el pegado automático |
| "Micrófono no disponible" | El micrófono elegido ya no existe | Configurar → elegir "Sistema (por defecto)" |
| El texto sale peor que antes | Diferencias del modo por lotes | Poner `"batch_size": 0` en `config.json` para volver al modo clásico |
| El programa no arranca | Dependencias faltantes | Ejecutar `python main.py` desde PowerShell para ver el error, o revisar `data/voz.log` |

## 🔧 Desarrollo

```powershell
python -m pytest -q
```

```powershell
.\build.ps1
```

`build.ps1` compila con PyInstaller y conserva `config.json`, `data\` y el modelo descargado de `dist\voz\`.

## 📄 Licencia

MIT
