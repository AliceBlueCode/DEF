# DEF(kari) — Plataforma Creativa de IA Multimodal

[日本語版README はこちら »](README.md) | [English README »](README_en.md) | [繁體中文版 »](README_zh-TW.md) | [简体中文版 »](README_zh-CN.md) | [한국어 README »](README_ko.md)

> **Dialogue × Emotion × Fable**\
> Con tus personajes, durante años, en cualquier lugar.

-----

## ¿Qué es DEF(kari)?

DEF(kari) es una plataforma creativa de IA local-first que integra generación de texto, voz e imagen.

En lugar de confiar tu contenido creativo a los términos de servicio y políticas de contenido de servicios en la nube, DEF(kari) proporciona **la base para generar y mantener los personajes e historias que deseas, en tu propio entorno, con tus propias manos.**

-----

## ¿Sin GPU? Aún puedes empezar.

DEF es local-first, pero no necesitas un entorno local para comenzar.

Usando APIs externas (Gemini / OpenAI / Anthropic, etc.), la generación de texto y síntesis de voz funcionan sin GPU. La generación de imágenes requiere una API de T2I (Civitai / Hugging Face) o un entorno GPU local.

Una vez que tu configuración local esté lista, puedes cambiar a operación completamente offline en cualquier momento.

-----

## Capturas de pantalla

### Modo Chat
![Chat](docs/images/chat.png)

### Modo Sesión
![Session](docs/images/session.png)

### Modo Episodio
![Episode](docs/images/episode.png)

### Personaje
![Character](docs/images/character.png)

-----

## Características principales

- **Local-First:** LLM, TTS y T2I funcionan completamente en local. También soporta respaldo con API externa
- **No requiere GPU para empezar:** Texto + voz funciona vía APIs externas. Cambia a GPU local cuando quieras
- **Integración de 3 modalidades:** Texto, voz e imagen funcionan juntos como una experiencia creativa continua
- **3 modos:** Chat (diálogo 1 a 1), Sesión (múltiples IAs + humanos en la misma mesa), Episodio (escritura de novelas + generación de candidatos por IA)
- **Persistencia de personajes:** El historial de diálogo, emociones y assets generados se persisten — retoma donde lo dejaste tras reiniciar
- **Patrón Adaptador:** Cambia libremente entre 4 backends de LLM, 4 de TTS y 4 de T2I
- **Zonificación:** Separación clara entre datos públicos y privados. Los assets generados quedan excluidos de Git

-----

## Backends compatibles

| Capa | Local (GPU) | API externa (sin GPU) |
|---|---|---|
| **LLM (texto)** | Text Generation WebUI / Ollama | Gemini API / OpenAI API / Anthropic Claude API |
| **TTS (voz)** | VOICEVOX / Kokoro TTS / Irodori-TTS | Gemini TTS API |
| **T2I (imagen)** | Automatic1111 / ComfyUI | Civitai API / Hugging Face API |

-----

## Inicio rápido

```bash
git clone https://github.com/AliceBlueCode/DEF.git
cd DEF
pip install -r requirements.txt
cp .env.example .env   # Configura backends y claves de API
streamlit run def_kari/app.py
```

Selecciona los backends de LLM, TTS y T2I desde la pestaña de Configuración.
Las claves de API se almacenan cifradas mediante "Gestión de claves API" en la pestaña de Configuración.
Para usar backends locales (TGW, VOICEVOX, A1111, etc.), configura las rutas de directorio en `.env`.

-----

## Nuestra postura sobre la libertad creativa

**Los creadores son libres de crear lo que deseen. Sin embargo, los creadores asumen toda la responsabilidad de sus creaciones.**

DEF(kari) está diseñado en base a este principio.

Cuando una herramienta interviene de forma preventiva en el contenido creativo, infringe la libertad de expresión del creador. DEF(kari) no censura ni bloquea contenido en actividades creativas locales.

### Separación clara entre lo público y lo privado

Lo que DEF(kari) protege es **la frontera entre lo público y lo privado**, no el acto creativo privado en sí mismo.

**Privado (creación local):**
Este es el dominio donde la libertad del creador está completamente garantizada. DEF(kari) no interviene aquí en absoluto. El filtro de seguridad (F-8) es simplemente una "herramienta de control de visualización" que los usuarios pueden desactivar. Nunca impide la generación en sí.

**Público (publicación en GitHub o plataformas externas):**
Este es el dominio donde se aplican las reglas sociales, derechos de autor y decencia pública. DEF(kari) proporciona soporte técnico a través de campos `content_policy`, zonificación (F-16) y scripts de verificación de publicación (F-25) para evitar que los creadores publiquen contenido privado de forma involuntaria.

Todo juicio y responsabilidad respecto al contenido creativo, su publicación y uso pertenecen al creador.

-----

## Licencia

Este software se distribuye bajo la [Licencia Pública General Affero de GNU v3.0 (AGPL v3)](https://www.gnu.org/licenses/agpl-3.0.html).

Copyright (C) 2026 AliceBlueCode

- Libre de usar, modificar y distribuir
- Si distribuyes versiones modificadas, debes publicar el código fuente bajo AGPL v3
- Si ofreces versiones modificadas a través de una red, también se requiere la divulgación del código fuente

> Consulta el archivo `LICENSE` para más detalles.

-----

## Contribuciones

Consulta `CONTRIBUTING.md`.

-----

## Términos de uso

Consulta `TERMS.md`. Este software está destinado únicamente a **usuarios mayores de 18 años**.

-----

## Créditos

DEF(kari) fue diseñado, implementado y documentado con la colaboración de:

- **Filosofía de diseño, diseño básico, discusión:** [ChatGPT](https://chatgpt.com/) (OpenAI)
- **Implementación, documentación, pruebas:** [Claude](https://claude.ai/) (Anthropic)
- **Revisión de diseño:** [Gemini](https://gemini.google.com/) (Google)
- **Consulta, acompañamiento:** [Copilot](https://copilot.microsoft.com/) (Microsoft)

Este proyecto fue construido mediante desarrollo impulsado por IA. Todas las decisiones de diseño y la responsabilidad final pertenecen al autor (AliceBlueCode).
