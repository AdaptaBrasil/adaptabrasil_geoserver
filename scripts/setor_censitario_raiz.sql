-- Setor Censitário (sep 10) como setor de verdade, igual aos outros:
-- raiz de nível 1 (110000) filha do indicador 0, e os 44 indicadores de
-- nível 6 (110021 a 110064) pendurados nela. Assim a mv_hierarchy passa a
-- incluí-los, com sep_order_by, e o app deixa de usar a raiz virtual.
--
-- Também coloca o setor em primeiro na home (sep.order_by = 0).
-- Depois de rodar: reinicie o app.

BEGIN;

SET search_path = adaptabrasil_aluana, public;

-- 1. Raiz de nível 1 do setor
INSERT INTO indicator (id, name, title, shortname, simple_description,
                       complete_description, level, sep_id, geoobjecttype_id, source)
VALUES (110000, 'Setor Censitário', 'Setor Censitário', 'Setor Censitário',
        'Indicadores calculados por setor censitário.',
        'Indicadores calculados por setor censitário.',
        1, 10, 1, 'AdaptaBrasil MCTI')
ON CONFLICT (id) DO NOTHING;

-- 2. Raiz ligada ao indicador 0, como as outras raízes
INSERT INTO indicator_indicator (indicator_id_master, indicator_id_detail)
VALUES (0, 110000)
ON CONFLICT DO NOTHING;

-- 3. Indicadores do setor ligados à raiz (só os que ainda não têm pai)
INSERT INTO indicator_indicator (indicator_id_master, indicator_id_detail)
SELECT 110000, i.id
FROM indicator i
WHERE i.sep_id = 10
  AND i.id <> 110000
  AND NOT EXISTS (SELECT 1 FROM indicator_indicator ii
                  WHERE ii.indicator_id_detail = i.id)
ON CONFLICT DO NOTHING;

-- 4. Setor Censitário em primeiro na home
UPDATE sep SET order_by = 0 WHERE id = 10;

-- 5. Recalcula as views (mv_hierarchy depende de mv_indiclevelyears)
REFRESH MATERIALIZED VIEW mv_indiclevelyears;
REFRESH MATERIALIZED VIEW mv_hierarchy;

-- Conferência: deve mostrar 110000 com sep_order_by = 0 e 44 filhos
SELECT id, shortname, level, sep_order_by
FROM mv_hierarchy WHERE indicator_id_master = 0 ORDER BY sep_order_by, id;

SELECT count(*) AS filhos_de_110000
FROM mv_hierarchy WHERE indicator_id_master = 110000;

COMMIT;
