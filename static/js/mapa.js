/*
 * Mapa dos indicadores, no modelo da Sala de Situação do INPE.
 *
 * Uma única layer do GeoServer (SQL view parametrizada) serve todos os
 * indicadores. O recorte vai em cada requisição:
 *   VIEWPARAMS = indicador:<id>;ano:<ano>;cenario:<id ou 0 = sem cenário>
 *   STYLES     = <prefixo><legend_id>
 *
 * A configuração vem do Flask em window.MAPA_CONFIG.
 */
(function () {
    "use strict";

    const cfg = window.MAPA_CONFIG;

    const estado = {
        indicador: null,   // resposta de /api/indicadores/<id>
        ano: null,
        cenario: null,
        botaoAtivo: null,
    };

    // ---------- Mapa ----------

    const fonteIndicador = new ol.source.ImageWMS({
        url: cfg.wmsUrl,
        params: { LAYERS: cfg.layer, VERSION: "1.1.1", FORMAT: "image/png", TRANSPARENT: true },
        serverType: "geoserver",
        crossOrigin: "anonymous",
    });
    const camadaIndicador = new ol.layer.Image({ source: fonteIndicador, visible: false });

    const camadaFundo = new ol.layer.Image({
        source: new ol.source.ImageWMS({
            url: cfg.wmsUrl,
            params: { LAYERS: cfg.layerFundo, VERSION: "1.1.1", FORMAT: "image/png" },
            serverType: "geoserver",
            crossOrigin: "anonymous",
        }),
    });

    const map = new ol.Map({
        target: "map",
        layers: [camadaFundo, camadaIndicador],
        view: new ol.View({ center: ol.proj.fromLonLat([-52.5, -16]), zoom: 4.75 }),
    });

    function viewparams() {
        return `indicador:${estado.indicador.id};ano:${estado.ano};cenario:${estado.cenario}`;
    }

    function atualizarMapa() {
        fonteIndicador.updateParams({
            VIEWPARAMS: viewparams(),
            STYLES: cfg.prefixoEstilo + estado.indicador.legenda,
        });
        camadaIndicador.setVisible(true);
        atualizarDownloads();
    }

    // ---------- Árvore de indicadores ----------

    function criarNo(no) {
        const li = document.createElement("li");
        const linha = document.createElement("div");
        linha.className = "no-indicador";

        const seta = document.createElement("button");
        seta.type = "button";
        seta.className = "seta";
        seta.textContent = no.filhos.length ? "▸" : "";
        seta.disabled = !no.filhos.length;
        seta.setAttribute("aria-label", "Expandir");

        const botao = document.createElement("button");
        botao.type = "button";
        botao.className = "nome-indicador";
        botao.textContent = no.nome;
        botao.title = no.titulo || no.nome;
        botao.addEventListener("click", () => selecionarIndicador(no.id, botao));

        linha.append(seta, botao);
        li.appendChild(linha);

        if (no.filhos.length) {
            const ul = document.createElement("ul");
            ul.hidden = true;
            no.filhos.forEach(f => ul.appendChild(criarNo(f)));
            li.appendChild(ul);
            seta.addEventListener("click", () => {
                ul.hidden = !ul.hidden;
                seta.textContent = ul.hidden ? "▸" : "▾";
            });
        }
        return li;
    }

    async function carregarArvore() {
        const raiz = await (await fetch(`/api/arvore/${cfg.raiz}`)).json();
        const ul = document.getElementById("arvore");
        raiz.filhos.forEach(f => ul.appendChild(criarNo(f)));
    }

    // ---------- Seleção de indicador, ano e cenário ----------

    async function selecionarIndicador(id, botao) {
        if (estado.botaoAtivo) estado.botaoAtivo.classList.remove("ativo");
        estado.botaoAtivo = botao;
        botao.classList.add("ativo");

        const resposta = await fetch(`/api/indicadores/${id}`);
        const dados = await resposta.json();
        estado.indicador = dados;

        document.getElementById("indicador-nome").textContent = dados.titulo || dados.nome;
        const painel = document.getElementById("painel-indicador");
        painel.hidden = false;

        if (!dados.opcoes.length) {
            document.getElementById("sem-dados").hidden = false;
            document.getElementById("controles").hidden = true;
            camadaIndicador.setVisible(false);
            return;
        }
        document.getElementById("sem-dados").hidden = true;
        document.getElementById("controles").hidden = false;

        // Começa pelo dado do presente (sem cenário), se houver
        const inicial = dados.opcoes.find(o => o.cenario === 0) || dados.opcoes[0];
        estado.ano = inicial.ano;
        estado.cenario = inicial.cenario;

        preencherAnos();
        preencherCenarios();
        desenharLegenda(dados.itens_legenda);
        atualizarMapa();
    }

    function preencherAnos() {
        const anos = [...new Set(estado.indicador.opcoes.map(o => o.ano))];
        const select = document.getElementById("ano");
        select.replaceChildren(...anos.map(a => new Option(a, a, false, a === estado.ano)));
    }

    function preencherCenarios() {
        const doAno = estado.indicador.opcoes.filter(o => o.ano === estado.ano);
        if (!doAno.some(o => o.cenario === estado.cenario)) estado.cenario = doAno[0].cenario;
        const select = document.getElementById("cenario");
        select.replaceChildren(...doAno.map(o =>
            new Option(o.nome_cenario, o.cenario, false, o.cenario === estado.cenario)));
        select.disabled = doAno.length === 1;
    }

    document.getElementById("ano").addEventListener("change", e => {
        estado.ano = Number(e.target.value);
        preencherCenarios();
        atualizarMapa();
    });

    document.getElementById("cenario").addEventListener("change", e => {
        estado.cenario = Number(e.target.value);
        atualizarMapa();
    });

    // ---------- Legenda ----------

    function desenharLegenda(itens) {
        const ul = document.getElementById("legenda");
        ul.replaceChildren(...itens.map(item => {
            const li = document.createElement("li");
            const cor = document.createElement("span");
            cor.className = "cor";
            cor.style.background = item.cor;
            const faixa = item.min === null ? "" : ` (${item.min} a ${item.max})`;
            li.append(cor, document.createTextNode(item.rotulo + faixa));
            return li;
        }));
    }

    // ---------- Valor no clique (GetFeatureInfo) ----------

    const info = document.getElementById("info");

    map.on("singleclick", async evt => {
        if (!camadaIndicador.getVisible()) return;
        const url = fonteIndicador.getFeatureInfoUrl(
            evt.coordinate, map.getView().getResolution(), "EPSG:3857",
            { INFO_FORMAT: "application/json", FEATURE_COUNT: 1 });
        try {
            const json = await (await fetch(url)).json();
            const f = json.features && json.features[0];
            if (!f) { info.hidden = true; return; }
            const valor = f.properties.value === null ? "Dado indisponível"
                : Number(f.properties.value).toLocaleString("pt-BR", { maximumFractionDigits: 4 });
            info.replaceChildren();
            const nome = document.createElement("strong");
            nome.textContent = f.properties.name;
            info.append(nome, document.createElement("br"), document.createTextNode(`Valor: ${valor}`));
            info.hidden = false;
        } catch (e) {
            console.error("Falha no GetFeatureInfo", e);
        }
    });

    // ---------- Downloads (WFS) ----------

    function urlWfs(formato) {
        const params = new URLSearchParams({
            service: "WFS", version: "1.0.0", request: "GetFeature",
            typeName: cfg.layer, outputFormat: formato, viewparams: viewparams(),
        });
        if (formato === "csv") params.set("propertyName", "geoobject_id,name,value");
        return cfg.wmsUrl.replace(/\/wms$/, "/ows") + "?" + params.toString();
    }

    function atualizarDownloads() {
        document.getElementById("baixar-csv").href = urlWfs("csv");
        document.getElementById("baixar-shp").href = urlWfs("SHAPE-ZIP");
    }

    carregarArvore().catch(e => console.error("Falha ao carregar a árvore de indicadores", e));
})();
