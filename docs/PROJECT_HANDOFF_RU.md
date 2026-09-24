# LCBMobile: handoff для другой LLM

Обновлено: 2026-09-24, `America/Sao_Paulo`.

Этот документ описывает текущую архитектуру, последние изменения и точную
границу загрузки сторонних видео. Перед любым утверждением о текущем состоянии
нужно заново проверить Git, Windows runtime, Mac backup и YouTube. Старый лог,
успешный exit code или строка в локальной БД не доказывают публикацию.

## 1. Что делает проект

Репозиторий: `https://github.com/tabuugroove-sys/lcbmobile`.

Рабочая ветка: `claude/create-news-feed-yMBpb`.

Локальный checkout:
`/Users/a1111/Documents/Codex/2026-04-29/github/lcbmobile`.

LCBMobile автоматически:

1. читает RSS с бразильскими новостями;
2. оставляет темы около музыки, музыкантов, артистов, концертов и релизов;
3. дедуплицирует уже обработанные и опубликованные сюжеты;
4. ранжирует кандидатов по свежести, известности артиста, реакции YouTube и
   подтверждённым drama-сигналам;
5. пишет сценарий на pt-BR;
6. генерирует ElevenLabs voice-over;
7. собирает вертикальный Short 1080x1920 с субтитрами, фото и доступными
   архивными видео;
8. публикует через YouTube Data API;
9. проверяет реальное увеличение числа роликов в uploads playlist;
10. включает резервные контуры, если основной runtime пропустил слот.

Telegram и Instagram не являются обязательными для текущего YouTube-контура.
Не считать их ошибку доказательством неудачной публикации на YouTube.

## 2. Где реально выполняется автопостинг

### Основной runtime: Windows server

- SSH alias: `capytime`; IP не записывать в репозиторий.
- Runtime: `C:\lcbmobile-news`.
- Это копия runtime-файлов, не Git checkout.
- Scheduled Task: `LCBMobile News Primary`, user `SYSTEM`.
- Watchdog запускается каждые пять минут.
- Слоты BRT: `09:13`, `14:13`, `19:13`.
- Ожидаемое число Shorts после слотов: `1`, `2`, `3`.
- Entrypoint: `scripts/run_server_primary.ps1`.
- Gate/orchestrator: `scripts/local_backup_runner.py`.
- Pipeline timeout: 2700 секунд.

Runner перед рендером читает uploads playlist канала. Если требуемое число
Shorts уже есть, публикация пропускается. После upload он повторно читает
YouTube и считает успехом только увеличение счётчика.

Секреты находятся в `C:\lcbmobile-news\secrets`. Никогда не выводить их
значения в чат, лог, handoff или коммит.

### Первый backup: Mac

- LaunchAgent: `com.tabuugroove.lcbmobile.local-backup`.
- Runtime: `~/.local/share/lcbmobile-backup`.
- Проверка каждые пять минут.
- Слоты: `09:28`, `14:28`, `19:28` BRT, через 15 минут после Windows.
- Перед публикацией используется тот же реальный YouTube count gate.

### Второй backup: GitHub Actions

- Workflow: `.github/workflows/pipeline.yml`.
- Слоты: `10:13`, `15:13`, `20:13` BRT.
- Это облачный fallback через час после Windows-слота.
- Scheduled run публикует только в YouTube.
- При пропуске квоты workflow сообщает в urgent bot.
- Ручной `workflow_dispatch` сохранён.

Не выключать без отдельного запроса другие workflows: horizontal Top 5,
comment responder, dashboard и отдельный LOOXX/Suno pipeline.

## 3. Текущий production pipeline

Основной orchestration находится в `src/pipeline.py`.

Важные правила:

- музыка остаётся hard gate;
- drama влияет на приоритет, но не разрешает придумывать факты;
- предпочтительна новость, для которой найден визуальный материал;
- если rich-media фильтр не пропустил ни одну новость, работает
  `_select_with_classic_fallback()` и публикуется старый графический вариант;
- отсутствие подходящего видео не должно отменять дневной слот;
- финальное доказательство публикации: YouTube id плюс readback uploads playlist.

Текущая озвучка:

- provider: ElevenLabs;
- voice id: `pNInz6obpgDQGcFmaJgB`;
- model: `eleven_multilingual_v2`;
- язык текста: pt-BR;
- speed: `0.82`.

Музыкальная подложка настроена через
`assets/audio/primeira_for_youtube.wav`, production volume `0.25`. Не менять
голос, трек или громкость молча.

## 4. Последние внесённые изменения

### Source-image fallback, commit `789b529`

Когда Wikimedia Commons не даёт подходящего фото,
`src/video/source_media.py` может скачать RSS/OpenGraph image из исходной
статьи. Такое изображение маркируется как
`Editorial source image; reuse rights not verified` и никогда не выдаётся за
CC-лицензированное.

### Photo-first selection и classic fallback

Кандидаты с реальным фото получают предпочтение. Если у всех кандидатов фото
нет, pipeline не останавливается: выбирается лучший сюжет и рендерится classic
format. Это сделано, чтобы слот не пропадал из-за media gate.

### Cloud fallback, commits `c1a10af` и `bc313b2`

- cloud dry-run может рендерить даже при недавнем посте;
- GitHub fallback снова стоит после Windows и Mac;
- он сверяет реальную дневную квоту YouTube до и после запуска;
- cloud fallback использует надёжный graphic/photo mode, а не обязательный
  набор `3 photos + 2 videos`.

### Semantic two-image curiosity hook, commit `3fe511c`

Первый кадр больше не дублирует одно фото слева и справа.

- слева основной герой заголовка;
- справа второй названный музыкант/оппонент, если он есть;
- иначе справа отдельный контекстный кадр из статьи: публика, место, событие,
  последствия и т.п.;
- рекомендации, аватары, логотипы и почти одинаковые размеры одного файла
  отбрасываются;
- если честного второго изображения нет, справа появляется редакционный
  teaser с интригой, а не копия первого фото.

Для этого были изменены:

- `src/editorial/music_filter.py`;
- `src/editorial/__init__.py`;
- `src/video/source_media.py`;
- `src/video/generator.py`;
- `tests/test_music_filter.py`;
- `tests/test_cinematic_short.py`.

Код был установлен на Windows primary и Mac backup. Зафиксированный deployment
commit: `9783d0b`. Последняя проверка этой правки: 53 targeted tests passed,
remote compile/import passed, hashes runtime-файлов совпали с репозиторием.
Это историческое доказательство deployment, а не доказательство сегодняшнего
поста.

## 5. Дедупликация

Дедуп работает на нескольких уровнях:

- нормализованный URL/fingerprint;
- content hash заголовка/сюжета;
- защита от повторов внутри одного run;
- локальная SQLite history;
- перед публикацией runtime сверяет реальный дневной счётчик YouTube.

Windows, Mac и GitHub не используют одну общую SQLite. Поэтому защита между
разными runtime зависит прежде всего от uploads-playlist count gate и remote
publication data. Не делать вывод о межсерверном дедупе только по локальной БД.

## 6. Медиа: три разных режима прав

В проекте нет одного глобального copyright switch. Есть три независимых пути.

### A. Wikimedia Commons photos

Файл: `src/video/commons_media.py`.

- `ALLOWED_LICENSE_PREFIXES = ("CC BY ", "CC0", "Public domain")`.
- `_candidate()` отклоняет `CC BY-SA`, неизвестную или отсутствующую лицензию.
- Принимаются JPEG/PNG не меньше 400 px по короткой стороне.
- Имя и metadata должны соответствовать конкретному артисту.
- Logo/poster/artwork/signature и другие нерелевантные файлы отбрасываются.
- Принятые assets записываются в `licensed_media/rights_manifest.json`.

### B. Source article photos

Файл: `src/video/source_media.py`.

- Загружаются RSS/OpenGraph и подходящие изображения из тела статьи.
- Разрешены только HTTP(S), размер ограничен 20 MB.
- Минимум 300 px по короткой стороне.
- Near-duplicate изображения отбрасываются perceptual hash проверкой.
- Права явно записываются как `reuse rights not verified`.

Это operational fallback, а не подтверждение права на повторное использование.

### C. Video footage

Файл: `src/video/commons_video.py`.

- `CURATED_VIDEOS` содержит вручную добавленные и проверенные Commons clips.
- Сейчас resolver знает только заранее внесённые записи для нескольких
  артистов, включая Lady Gaga, Shakira и Dua Lipa.
- `fetch_licensed_artist_videos()` скачивает только `source_url` из этого
  словаря.
- Для каждого файла сохраняются creator, license, license URL, source page,
  source URL и SHA-256 в `licensed_video/rights_manifest.json`.
- Автоматического поиска видео по Commons, YouTube или всему web нет.

## 7. Ограничения на скачивание видео с YouTube: точная правда

### Что было вписано в проект

1. В `src/video/commons_video.py` production video resolver сделан
   whitelist-only через `CURATED_VIDEOS`.
2. В комментарии над словарём прямо указано, что dynamic video search исключён
   из unattended production.
3. В `docs/legal_video_sources.md` записано правило: обычные YouTube uploads не
   считаются pipeline-ready без явной reuse license/permission; YouTube CC
   допускается только при подтверждённой Creative Commons Attribution license.
4. В `docs/daily_music_video_sourcing_2026-06-09.md` обычные YouTube/social
   результаты без разрешения отмечены как blocked для автоматического монтажа.
5. `resolve_visual_media()` в `src/video/generator.py` подключает Commons
   photos, source-article photos и curated Commons videos. YouTube downloader в
   этой функции отсутствует.

### Чего в коде нет

- Нет `BLOCK_YOUTUBE_DOWNLOAD`.
- Нет проверки вида `if host == youtube.com: reject`.
- Нет отдельного запрета на YouTube URL.
- Нет `yt-dlp` или `youtube-dl` в `requirements.txt`.
- Нет cookies/browser-auth/DRM bypass.
- Нет функции, которая принимает произвольный YouTube URL, скачивает ролик и
  передаёт его в монтаж.

Поэтому правильная формулировка: **YouTube downloading не заблокирован отдельным
guard; произвольный YouTube ingestion просто не реализован и не подключён к
production**. Удалять один `if` бессмысленно, потому что такого `if` нет.

### Почему выбран именно такой production boundary

Монтаж, crop, субтитры, voice-over и использование короткого фрагмента сами по
себе не создают разрешение правообладателя. Поэтому unattended runtime сейчас
использует curated assets с записанным происхождением или падает обратно в
classic/photo format, а не скачивает случайный YouTube upload.

Это ограничение кода надо отличать от правил конкретной LLM/продукта. Внешние
правила агента не лежат в Git и не удаляются изменением репозитория.

## 8. Как технически добавить YouTube ingestion в будущем

Это новая подсистема, а не снятие существующего флага. Минимальный корректный
план:

1. создать отдельный adapter, например `src/video/youtube_media.py`;
2. принимать только URL с зафиксированным основанием использования: owner,
   written permission или подтверждённая compatible reuse license;
3. хранить video id, original URL, channel, license/permission evidence,
   fetched timestamp и SHA-256;
4. добавить лимиты размера/длительности, timeout, retry и проверку контейнера;
5. вырезать короткие сцены без original audio;
6. добавить source-level дедуп, чтобы один ролик не повторялся в следующих
   Shorts;
7. записывать всё в rights/source manifest;
8. подключить adapter в `resolve_visual_media()` после явного feature flag;
9. установить downloader и ffmpeg-зависимости на Windows, Mac и GitHub runner;
10. добавить unit tests, dry-run render и visual review до production deploy.

Наличие публичного URL или выбор пользователем ролика не должно автоматически
превращаться в ложную запись `CC BY`.

## 9. Где продолжать работу

- Общий pipeline: `src/pipeline.py`.
- Конфигурация: `src/config.py`.
- Ranking/music filter: `src/editorial/music_filter.py`.
- Renderer/media composition: `src/video/generator.py`.
- Commons photos: `src/video/commons_media.py`.
- Source article photos: `src/video/source_media.py`.
- Curated videos: `src/video/commons_video.py`.
- YouTube publisher: `src/publisher/youtube.py`.
- Windows runner: `scripts/run_server_primary.ps1`.
- Backup/count gate: `scripts/local_backup_runner.py`.
- GitHub fallback: `.github/workflows/pipeline.yml`.
- Подробный английский handoff: `docs/LLM_HANDOFF.md`.
- Server runbook: `docs/SERVER_PRIMARY.md`.
- Mac runbook: `docs/LOCAL_MAC_BACKUP.md`.

## 10. Обязательная последовательность проверки

1. `git status --short`; не затирать чужие изменения.
2. Проверить текущую ветку и последние commits.
3. Читать точные функции до правок, не полагаться только на этот handoff.
4. Добавить/обновить тесты.
5. Запустить tests и `git diff --check`.
6. Commit и push активной ветки.
7. Явно скопировать изменённые runtime-файлы на Windows, потому что там нет
   Git checkout.
8. Обновить Mac runtime, если менялся общий код.
9. Проверить Scheduled Task/LaunchAgent и логи.
10. На следующем слоте подтвердить YouTube id и uploads-playlist readback.

Никогда не писать «готово» только потому, что рендер создал MP4 или uploader
завершился с code 0. Для operational результата нужен ответ самого YouTube.
