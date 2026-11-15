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
        pedido: 0,         // conta as seleções, para descartar respostas antigas
        estado: 0,         // id na view state; 0 = Brasil
        municipio: 0,      // id na view county; 0 = todos os municípios do estado
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

    const VISTA_BRASIL = { center: ol.proj.fromLonLat([-52.5, -16]), zoom: 4.75 };

    const map = new ol.Map({
        target: "map",
        layers: [camadaFundo, camadaIndicador],
        view: new ol.View({ ...VISTA_BRASIL }),
    });

    // ---------- Rodapé: andamento e tempo de carregamento ----------

    /*
     * O GeoServer devolve a imagem de uma vez, sem informar o andamento.
     * A barra marca as etapas (consulta do indicador, pedido da imagem) e,
     * enquanto o GeoServer gera a imagem, avança devagar em direção a 95%;
     * fecha em 100% quando a imagem chega. O tempo vai do clique até a
     * imagem aparecer no mapa.
     */
    const progresso = (function () {
        const caixa = document.querySelector("#rodape .progress");
        const barra = document.getElementById("rodape-barra");
        const texto = document.getElementById("rodape-texto");
        let inicio = null;
        let rotulo = "";
        let valor = 0;
        let timer = null;

        function definir(v) {
            valor = v;
            barra.style.width = `${v}%`;
            caixa.setAttribute("aria-valuenow", Math.round(v));
        }

        function parar() {
            clearInterval(timer);
            timer = null;
            barra.classList.remove("progress-bar-striped", "progress-bar-animated");
        }

        return {
            ativo: () => inicio !== null,

            iniciar(nome) {
                parar();
                inicio = performance.now();
                rotulo = nome;
                caixa.hidden = false;
                barra.classList.remove("bg-danger");
                barra.classList.add("bg-success", "progress-bar-striped", "progress-bar-animated");
                definir(5);
                texto.textContent = `Carregando ${nome}…`;
            },

            avancar(v) {
                if (inicio !== null && v > valor) definir(v);
            },

            aguardarImagem() {
                if (inicio === null) return;
                clearInterval(timer);
                timer = setInterval(() => this.avancar(valor + (95 - valor) * 0.06), 200);
            },

            concluir() {
                if (inicio === null) return;
                const segundos = (performance.now() - inicio) / 1000;
                parar();
                definir(100);
                inicio = null;
                const s = segundos.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
                texto.textContent = `${rotulo}: mapa carregado em ${s} s`;
            },

            falhar(mensagem) {
                parar();
                barra.classList.replace("bg-success", "bg-danger");
                definir(100);
                inicio = null;
                texto.textContent = `${rotulo}: ${mensagem}`;
            },

            encerrar(mensagem) {
                parar();
                caixa.hidden = true;
                definir(0);
                inicio = null;
                texto.textContent = mensagem;
            },
        };
    })();

    function rotuloAtual() {
        const cenario = document.getElementById("cenario");
        const nomeCenario = cenario.options[cenario.selectedIndex]?.text;
        const nome = estado.indicador.titulo || estado.indicador.nome;
        return `${nome} (${estado.ano}${nomeCenario ? ", " + nomeCenario : ""}) · ${nomeArea()}`;
    }

    // Só a última imagem pedida conta: uma resposta atrasada de um pedido
    // anterior não pode encerrar a contagem do mapa atual.
    let ultimaImagem = null;

    fonteIndicador.on("imageloadstart", e => {
        ultimaImagem = e.image;
        // Mover ou aproximar o mapa também gera uma imagem nova
        if (!progresso.ativo()) progresso.iniciar(rotuloAtual());
        progresso.avancar(35);
        progresso.aguardarImagem();
    });
    fonteIndicador.on("imageloadend", e => {
        if (e.image === ultimaImagem) progresso.concluir();
    });
    fonteIndicador.on("imageloaderror", e => {
        if (e.image === ultimaImagem) progresso.falhar("falha ao carregar o mapa");
    });

    function viewparams() {
        return `indicador:${estado.indicador.id};ano:${estado.ano};cenario:${estado.cenario}`
            + `;estado:${estado.estado};municipio:${estado.municipio}`;
    }

    // ---------- Filtros de Estado e Município ----------

    const selectEstado = document.getElementById("estado");
    const selectMunicipio = document.getElementById("municipio");

    function nomeArea() {
        if (estado.municipio) {
            const sigla = selectEstado.selectedOptions[0].dataset.sigla;
            return `${selectMunicipio.selectedOptions[0].text} (${sigla})`;
        }
        return selectEstado.selectedOptions[0].text;
    }

    async function carregarEstados() {
        const estados = await (await fetch("/api/estados")).json();
        selectEstado.append(...estados.map(e => {
            const opcao = new Option(e.nome, e.id);
            opcao.dataset.sigla = e.sigla;
            return opcao;
        }));
    }

    async function carregarMunicipios() {
        selectMunicipio.replaceChildren(new Option("Todos", 0, true, true));
        selectMunicipio.disabled = true;
        if (!estado.estado) return;
        const pedido = estado.estado;
        const municipios = await (await fetch(`/api/estados/${pedido}/municipios`)).json();
        // Outro estado foi escolhido enquanto este carregava
        if (pedido !== estado.estado) return;
        selectMunicipio.append(...municipios.map(m => new Option(m.nome, m.id)));
        selectMunicipio.disabled = false;
    }

    async function enquadrarArea() {
        const view = map.getView();
        if (!estado.estado) {
            view.animate({ ...VISTA_BRASIL, duration: 400 });
            return;
        }
        const area = `${estado.estado}/${estado.municipio}`;
        const params = new URLSearchParams({ estado: estado.estado, municipio: estado.municipio });
        const resposta = await fetch(`/api/limites?${params}`);
        // A área mudou enquanto os limites carregavam
        if (!resposta.ok || area !== `${estado.estado}/${estado.municipio}`) return;
        const extent = ol.proj.transformExtent(await resposta.json(), "EPSG:4326", "EPSG:3857");
        view.fit(extent, { padding: [30, 30, 30, 30], duration: 400, maxZoom: 12 });
    }

    function aplicarArea() {
        enquadrarArea().catch(e => console.error("Falha ao enquadrar a área", e));
        // Sem indicador escolhido, o filtro vale quando ele for escolhido
        if (!estado.indicador || !estado.indicador.opcoes.length) return;
        progresso.iniciar(rotuloAtual());
        atualizarMapa();
    }

    selectEstado.addEventListener("change", () => {
        estado.estado = Number(selectEstado.value);
        estado.municipio = 0;
        carregarMunicipios().catch(e => console.error("Falha ao carregar os municípios", e));
        aplicarArea();
    });

    selectMunicipio.addEventListener("change", () => {
        estado.municipio = Number(selectMunicipio.value);
        aplicarArea();
    });

    function atualizarMapa() {
        const params = { VIEWPARAMS: viewparams(), STYLES: cfg.prefixoEstilo + estado.indicador.legenda };
        const atuais = fonteIndicador.getParams();
        // Mesmo mapa já na tela: o OpenLayers não pede imagem nova
        const igual = camadaIndicador.getVisible()
            && atuais.VIEWPARAMS === params.VIEWPARAMS && atuais.STYLES === params.STYLES;
        fonteIndicador.updateParams(params);
        camadaIndicador.setVisible(true);
        atualizarDownloads();
        if (igual) progresso.concluir();
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

        const pedido = ++estado.pedido;
        progresso.iniciar(botao.textContent);
        progresso.avancar(15);

        let dados;
        try {
            const resposta = await fetch(`/api/indicadores/${id}`);
            if (!resposta.ok) throw new Error(`HTTP ${resposta.status}`);
            dados = await resposta.json();
        } catch (e) {
            console.error("Falha ao consultar o indicador", e);
            if (pedido === estado.pedido) progresso.falhar("falha ao consultar o indicador");
            return;
        }
        // Outro indicador foi escolhido enquanto este carregava
        if (pedido !== estado.pedido) return;
        progresso.avancar(30);
        estado.indicador = dados;

        document.getElementById("indicador-nome").textContent = dados.titulo || dados.nome;
        const painel = document.getElementById("painel-indicador");
        painel.hidden = false;

        if (!dados.opcoes.length) {
            document.getElementById("sem-dados").hidden = false;
            document.getElementById("controles").hidden = true;
            camadaIndicador.setVisible(false);
            progresso.encerrar(`${dados.titulo || dados.nome}: sem dados para exibir no mapa`);
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
        progresso.iniciar(rotuloAtual());
        atualizarMapa();
    });

    document.getElementById("cenario").addEventListener("change", e => {
        estado.cenario = Number(e.target.value);
        progresso.iniciar(rotuloAtual());
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
        // Sem a geometria; o id do geoobjeto sai na coluna FID (indicador.<id>)
        if (formato === "csv") params.set("propertyName", "name,value");
        return cfg.wmsUrl.replace(/\/wms$/, "/ows") + "?" + params.toString();
    }

    function atualizarDownloads() {
        document.getElementById("baixar-csv").href = urlWfs("csv");
        document.getElementById("baixar-shp").href = urlWfs("SHAPE-ZIP");
    }

    carregarArvore().catch(e => console.error("Falha ao carregar a árvore de indicadores", e));
    carregarEstados().catch(e => console.error("Falha ao carregar os estados", e));
})();
