"""Build a legal horizontal multi-news test video with ElevenLabs voiceover."""
from __future__ import annotations

import json

from src.config import ROOT

from . import build_legal_star_horizontal_test as base


OUT = ROOT / "out" / "legal_multinews_horizontal_test"

NEWS_ITEMS = [
    {
        "title": "Shakira será atração de uma das três cerimônias de abertura da Copa do Mundo; Anitta também fará apresentação",
        "source": "G1 Pop & Arte",
        "url": "https://g1.globo.com/pop-arte/musica/noticia/2026/06/05/shakira-sera-atracao-de-uma-das-tres-cerimonias-de-abertura-da-copa-do-mundo-anitta-tambem-fara-apresentacao.ghtml",
    },
    {
        "title": "Casamento de Dua Lipa e Callum Turner movimenta Sicília antes da cerimônia",
        "source": "G1 Pop & Arte",
        "url": "https://g1.globo.com/pop-arte/noticia/2026/06/05/casamento-de-dua-lipa-e-callum-turner-movimenta-sicilia.ghtml",
    },
    {
        "title": "Rock in Rio 2026 esgota em 2h ingressos para dias de Calvin Harris e Maroon 5",
        "source": "G1 Pop & Arte",
        "url": "https://g1.globo.com/pop-arte/noticia/2026/06/08/rock-in-rio-esgota-ingressos-para-dias-de-calvin-harris-e-maroon-5.ghtml",
    },
]

PACKAGE_NEWS = {
    "title": "LCB Pop Radar: Shakira, Dua Lipa e Calvin Harris",
    "source": "G1 Pop & Arte",
    "url": NEWS_ITEMS[0]["url"],
}

ASSETS = [
    {
        "id": "shakira_un_imagine",
        "name": "Shakira",
        "media_type": "video",
        "commons_title": 'File:Na ONU, Shakira canta "Imagine" e pede igualdade para todos.webm',
        "file": "shakira_un_imagine_720p.webm",
        "download_url": (
            "https://upload.wikimedia.org/wikipedia/commons/transcoded/2/21/"
            "Na_ONU%2C_Shakira_canta_%22Imagine%22_e_pede_igualdade_para_todos.webm/"
            "Na_ONU%2C_Shakira_canta_%22Imagine%22_e_pede_igualdade_para_todos.webm.720p.vp9.webm"
        ),
        "credit": 'Na ONU, Shakira canta "Imagine", video by ONU Brasil, CC BY 3.0',
        "display_credit": "ONU Brasil, CC BY 3.0",
        "source": "https://commons.wikimedia.org/wiki/File:Na_ONU,_Shakira_canta_%22Imagine%22_e_pede_igualdade_para_todos.webm",
        "license": "https://creativecommons.org/licenses/by/3.0/",
    },
    {
        "id": "shakira_davos",
        "name": "Shakira",
        "media_type": "video",
        "commons_title": "File:Davos 2017 - An Insight, An Idea with Shakira.webm",
        "file": "shakira_davos_480p.webm",
        "download_url": (
            "https://upload.wikimedia.org/wikipedia/commons/transcoded/d/de/"
            "Davos_2017_-_An_Insight%2C_An_Idea_with_Shakira.webm/"
            "Davos_2017_-_An_Insight%2C_An_Idea_with_Shakira.webm.480p.vp9.webm"
        ),
        "credit": "Davos 2017 - An Insight, An Idea with Shakira, video by World Economic Forum, CC BY 3.0",
        "display_credit": "World Economic Forum, CC BY 3.0",
        "source": "https://commons.wikimedia.org/wiki/File:Davos_2017_-_An_Insight,_An_Idea_with_Shakira.webm",
        "license": "https://creativecommons.org/licenses/by/3.0/",
    },
    {
        "id": "dua_radical",
        "name": "Dua Lipa",
        "media_type": "video",
        "commons_title": "File:All you need to know about Dua Lipa's new album 'Radical Optimism'.webm",
        "file": "dua_radical_optimism.webm",
        "download_url": "https://upload.wikimedia.org/wikipedia/commons/f/f2/All_you_need_to_know_about_Dua_Lipa%27s_new_album_%27Radical_Optimism%27.webm",
        "credit": "All you need to know about Dua Lipa's new album Radical Optimism, video by Warner Music New Zealand, CC BY 3.0",
        "display_credit": "Warner Music NZ, CC BY 3.0",
        "source": "https://commons.wikimedia.org/wiki/File:All_you_need_to_know_about_Dua_Lipa%27s_new_album_%27Radical_Optimism%27.webm",
        "license": "https://creativecommons.org/licenses/by/3.0/",
    },
    {
        "id": "dua_grammys",
        "name": "Dua Lipa",
        "media_type": "video",
        "commons_title": "File:Interview with Dua Lipa at the 2021 Grammys.webm",
        "file": "dua_grammys_interview.webm",
        "download_url": "https://upload.wikimedia.org/wikipedia/commons/0/0c/Interview_with_Dua_Lipa_at_the_2021_Grammys.webm",
        "credit": "Interview with Dua Lipa at the 2021 Grammys, video by Warner Music New Zealand, CC BY 3.0",
        "display_credit": "Warner Music NZ, CC BY 3.0",
        "source": "https://commons.wikimedia.org/wiki/File:Interview_with_Dua_Lipa_at_the_2021_Grammys.webm",
        "license": "https://creativecommons.org/licenses/by/3.0/",
    },
    {
        "id": "calvin_live_01",
        "name": "Calvin Harris",
        "media_type": "video",
        "commons_title": "File:Videos of Calvin Harris live in Bengaluru (2026) 01.webm",
        "file": "calvin_harris_bengaluru_01.webm",
        "download_url": "https://upload.wikimedia.org/wikipedia/commons/3/38/Videos_of_Calvin_Harris_live_in_Bengaluru_%282026%29_01.webm",
        "credit": "Calvin Harris live in Bengaluru 2026, video by Gpkp, CC BY-SA 4.0",
        "display_credit": "Gpkp, CC BY-SA 4.0",
        "source": "https://commons.wikimedia.org/wiki/File:Videos_of_Calvin_Harris_live_in_Bengaluru_(2026)_01.webm",
        "license": "https://creativecommons.org/licenses/by-sa/4.0/",
    },
    {
        "id": "calvin_live_03",
        "name": "Calvin Harris",
        "media_type": "video",
        "commons_title": "File:Videos of Calvin Harris live in Bengaluru (2026) 03.webm",
        "file": "calvin_harris_bengaluru_03.webm",
        "download_url": "https://upload.wikimedia.org/wikipedia/commons/e/ea/Videos_of_Calvin_Harris_live_in_Bengaluru_%282026%29_03.webm",
        "credit": "Calvin Harris live in Bengaluru 2026, video by Gpkp, CC BY-SA 4.0",
        "display_credit": "Gpkp, CC BY-SA 4.0",
        "source": "https://commons.wikimedia.org/wiki/File:Videos_of_Calvin_Harris_live_in_Bengaluru_(2026)_03.webm",
        "license": "https://creativecommons.org/licenses/by-sa/4.0/",
    },
    {
        "id": "calvin_live_04",
        "name": "Calvin Harris",
        "media_type": "video",
        "commons_title": "File:Videos of Calvin Harris live in Bengaluru (2026) 04.webm",
        "file": "calvin_harris_bengaluru_04.webm",
        "download_url": "https://upload.wikimedia.org/wikipedia/commons/0/0a/Videos_of_Calvin_Harris_live_in_Bengaluru_%282026%29_04.webm",
        "credit": "Calvin Harris live in Bengaluru 2026, video by Gpkp, CC BY-SA 4.0",
        "display_credit": "Gpkp, CC BY-SA 4.0",
        "source": "https://commons.wikimedia.org/wiki/File:Videos_of_Calvin_Harris_live_in_Bengaluru_(2026)_04.webm",
        "license": "https://creativecommons.org/licenses/by-sa/4.0/",
    },
]

SCENES = [
    {"asset_id": "shakira_un_imagine", "seek_start": 0.0, "duration": 7.0, "eyebrow": "NEWS 1  |  SHAKIRA", "title": "Copa chama Shakira", "body": "A abertura de 2026 vira palco global.", "crop_x": 0, "crop_y": 0},
    {"asset_id": "shakira_davos", "seek_start": 35.0, "duration": 7.0, "eyebrow": "NEWS 1  |  IMPACTO", "title": "Símbolo de Copa", "body": "A força dela vem do histórico mundial.", "crop_x": 70, "crop_y": 0},
    {"asset_id": "shakira_un_imagine", "seek_start": 10.0, "duration": 7.0, "eyebrow": "NEWS 1  |  PALCO", "title": "Voz e presença", "body": "Vídeo licenciado, áudio original mutado.", "crop_x": 120, "crop_y": 20},
    {"asset_id": "shakira_davos", "seek_start": 105.0, "duration": 7.0, "eyebrow": "NEWS 1  |  CONTEXTO", "title": "Nome internacional", "body": "A notícia ganha ritmo de boletim pop.", "crop_x": 30, "crop_y": 0},
    {"asset_id": "shakira_un_imagine", "seek_start": 28.0, "duration": 7.0, "eyebrow": "NEWS 1  |  FECHO", "title": "Anitta no contexto", "body": "O foco da primeira nota fica em Shakira.", "crop_x": 20, "crop_y": 0},
    {"asset_id": "dua_radical", "seek_start": 0.0, "duration": 7.0, "eyebrow": "NEWS 2  |  DUA LIPA", "title": "Sicília em movimento", "body": "A notícia acompanha o clima pré-casamento.", "crop_x": 0, "crop_y": 0},
    {"asset_id": "dua_grammys", "seek_start": 4.0, "duration": 7.0, "eyebrow": "NEWS 2  |  ESTRELA", "title": "Dua no centro", "body": "A edição usa vídeo oficial licenciado.", "crop_x": 70, "crop_y": 0},
    {"asset_id": "dua_radical", "seek_start": 12.0, "duration": 7.0, "eyebrow": "NEWS 2  |  POP", "title": "Casamento vira pauta", "body": "Sem foto parada: só cenas em movimento.", "crop_x": 120, "crop_y": 0},
    {"asset_id": "dua_grammys", "seek_start": 18.0, "duration": 7.0, "eyebrow": "NEWS 2  |  FOCO", "title": "Imagem editorial", "body": "A narração explica a notícia sem inventar.", "crop_x": 40, "crop_y": 0},
    {"asset_id": "dua_radical", "seek_start": 25.0, "duration": 7.0, "eyebrow": "NEWS 2  |  FECHO", "title": "Dua segue no radar", "body": "A segunda nota fecha com contexto pop.", "crop_x": 90, "crop_y": 0},
    {"asset_id": "calvin_live_01", "seek_start": 0.0, "duration": 7.0, "eyebrow": "NEWS 3  |  CALVIN HARRIS", "title": "Rock in Rio esgota", "body": "O dia de Calvin Harris sumiu em pouco mais de 2h.", "crop_x": 0, "crop_y": 0},
    {"asset_id": "calvin_live_03", "seek_start": 0.0, "duration": 7.0, "eyebrow": "NEWS 3  |  FESTIVAL", "title": "Line-up pesado", "body": "A notícia mostra a força do festival.", "crop_x": 80, "crop_y": 0},
    {"asset_id": "calvin_live_04", "seek_start": 0.0, "duration": 7.0, "eyebrow": "NEWS 3  |  PALCO", "title": "Set em destaque", "body": "Cortes curtos evitam bloco cru de show.", "crop_x": 120, "crop_y": 0},
    {"asset_id": "calvin_live_01", "seek_start": 7.0, "duration": 7.0, "eyebrow": "NEWS 3  |  RITMO", "title": "Venda acelerada", "body": "A edição cruza texto, legenda e vídeo.", "crop_x": 50, "crop_y": 0},
    {"asset_id": "calvin_live_03", "seek_start": 5.0, "duration": 7.0, "eyebrow": "FECHO  |  RADAR POP", "title": "Três notícias, um vídeo", "body": "Formato longo 16:9 para teste editorial.", "crop_x": 20, "crop_y": 0},
]

NARRATION_SEGMENTS = [
    (0.4, 7.0, "Primeiro destaque: Shakira voltou ao centro da conversa por causa da abertura da Copa do Mundo de 2026."),
    (7.0, 14.2, "Segundo a G1, ela será atração de uma das três cerimônias oficiais antes dos jogos."),
    (14.2, 21.4, "A escolha faz sentido porque Shakira já virou símbolo de Copa para muita gente ao redor do mundo."),
    (21.4, 28.5, "Nesta edição, o vídeo usa material licenciado, áudio original mutado e texto próprio na tela."),
    (28.5, 35.4, "Anitta também aparece na notícia, mas a primeira nota fecha com Shakira como personagem principal."),
    (35.4, 42.6, "Segundo destaque: Dua Lipa movimenta a Sicília com a notícia do casamento com Callum Turner."),
    (42.6, 49.8, "Aqui, a ideia não é mostrar foto parada: é usar vídeo legal da artista para dar vida à nota."),
    (49.8, 57.0, "O casamento vira assunto pop porque junta estrela global, bastidores de viagem e curiosidade pública."),
    (57.0, 64.2, "A narração fica em cima dos fatos da fonte, sem transformar rumor em confirmação."),
    (64.2, 71.4, "Assim, a segunda parte fica com cara de boletim editorial, não de recorte solto da internet."),
    (71.4, 78.6, "Terceiro destaque: Rock in Rio dois mil e vinte e seis esgotou rápido para Calvin Harris e Maroon Five."),
    (78.6, 85.8, "A G1 diz que os ingressos dos dias principais acabaram em pouco mais de duas horas."),
    (85.8, 93.0, "No dia de Calvin Harris, o apelo é de festival grande, pista cheia e line-up de peso."),
    (93.0, 100.2, "Os cortes de show são curtos, com legenda e narração, para deixar clara a edição jornalística."),
    (100.2, 108.0, "Esse é o modelo: várias notícias, cada uma com vídeo legal da estrela citada, em um único 16 por 9."),
]


def write_multinews_credits() -> None:
    (OUT / "credits.json").write_text(
        json.dumps(
            {
                "news_items": NEWS_ITEMS,
                "assets": ASSETS,
                "scenes": SCENES,
                "narration_segments": NARRATION_SEGMENTS,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    lines = ["News items:"]
    lines.extend(f"- {n['title']} | {n['source']} | {n['url']}" for n in NEWS_ITEMS)
    lines.append("")
    lines.append("Video assets:")
    lines.extend(f"- {a['credit']} | {a['source']} | {a['license']}" for a in ASSETS)
    (OUT / "credits.txt").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    base.OUT = OUT
    base.NEWS = PACKAGE_NEWS
    base.ASSETS = ASSETS
    base.SCENES = SCENES
    base.NARRATION_SEGMENTS = NARRATION_SEGMENTS
    base.download_assets()
    write_multinews_credits()
    base.synthesize_voice()
    video = base.build_video()
    print(f"created={video}")


if __name__ == "__main__":
    main()
