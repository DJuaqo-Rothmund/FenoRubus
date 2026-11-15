"""
scout_guide.py
==============
Guía interna de AeonScout: fichas de reconocimiento de PLAGAS, MALEZAS y ENFERMEDADES de
frambuesa, arándano y cranberry en el sur de Chile (Región de Los Ríos y alrededores).

Cada ficha dice cómo reconocerla (forma, color, tamaño, estructura), sus estadios, el daño o
síntoma, con qué se confunde y en qué cultivos aparece. La usa:

* el catálogo de AeonScout (las especies se agregan solas: `seed`);
* la ficha de cada especie (pantalla de la especie);
* la IA online (scout_ai): la lista de candidatas va en la consulta, así la respuesta cae
  en especies que la app conoce;
* la guía de cómo sacar las fotos (PHOTO_GUIDE).

Puro Python. Las fichas son una ayuda de campo, no reemplazan la identificación de un
especialista o laboratorio (sobre todo en enfermedades).
"""
from __future__ import annotations

import re
import unicodedata

REGION = "Región de Los Ríos, sur de Chile"
CROPS = {"F": "frambuesa", "A": "arandano", "C": "cranberry"}
CROP_NAMES = {"frambuesa": "Frambuesa", "arandano": "Arándano", "cranberry": "Cranberry"}
RANKS = ("especie", "género", "familia", "grupo")


def _sp(section, name, sci, crops, look, stages="", damage="", confuse="", kind="", rank="especie"):
    return {"section": section, "name": name, "scientific": sci, "crops": crops, "look": look,
            "stages": stages, "damage": damage, "confuse": confuse, "kind": kind, "rank": rank}


P, M, E = "plagas", "malezas", "enfermedades"

SPECIES: list[dict] = [
    # ================================================================== PLAGAS
    # --- Curculiónidos (burritos, cabritos, capachitos): adultos comen hojas; larvas, raíces
    _sp(P, "Cabrito del frambueso", "Aegorhinus superciliosus", "FA",
        "Gorgojo grande (12–16 mm), café oscuro a negro, cuerpo abultado y rugoso con escamas "
        "amarillentas; trompa corta y ancha; no vuela (élitros soldados).",
        "Larva blanca, curvada en «C», sin patas y con cabeza café, en raíces y cuello. Adulto de "
        "primavera a otoño, de noche en el follaje.",
        "Larvas barrenan raíces y corona (plantas débiles, cañas que se secan); adultos comen bordes "
        "de hojas y yemas.", "Otros burritos (Naupactus, Otiorhynchus): son más chicos y lisos.",
        "plaga"),
    _sp(P, "Burrito de la frambuesa", "Aegorhinus nodipennis", "FA",
        "Gorgojo café grisáceo con protuberancias (nódulos) en los élitros; 10–14 mm; no vuela.",
        "Larva ápoda blanca en raíces; adulto en follaje de noche.",
        "Similar al cabrito: raíces dañadas por larvas y hojas comidas por adultos.",
        "Aegorhinus superciliosus (más grande, sin nódulos marcados).", "plaga"),
    _sp(P, "Burrito de la vid", "Naupactus xanthographus", "FA",
        "Gorgojo de 10–14 mm, café grisáceo con líneas laterales blanco-amarillentas; trompa corta.",
        "Huevos en masas bajo la corteza; larva blanca en el suelo (raíces); adulto en verano.",
        "Adultos comen hojas desde el borde (mordeduras en media luna); larvas, raíces.",
        "Naupactus leucoloma (bandas blancas en el borde), Otiorhynchus (negro).", "plaga"),
    _sp(P, "Burrito de bandas blancas", "Naupactus leucoloma", "FAC",
        "Gorgojo gris parduzco de 8–12 mm con una banda blanca a cada lado del cuerpo (borde de "
        "élitros y tórax); cubierto de pelillos finos. Solo hembras (partenogenético).",
        "Larva blanca ápoda en el suelo, se alimenta de raíces y estolones (en cranberry, de las "
        "guías). Adulto de verano a otoño.",
        "Larvas cortan raíces y estolones: manchones amarillos o rojizos que se secan; adultos "
        "muerden bordes de hojas.", "Naupactus xanthographus (líneas más amarillas y anchas).",
        "plaga"),
    _sp(P, "Gorgojo negro de la vid", "Otiorhynchus sulcatus", "FAC",
        "Gorgojo negro mate de 8–10 mm, con pequeñas manchas de pelos amarillos en los élitros "
        "estriados; antenas acodadas; no vuela; activo de noche.",
        "Huevo diminuto, blanco a café; larva blanca ápoda en «C» con cabeza café, en raíces; pupa "
        "blanca en el suelo. Adultos desde fines de primavera.",
        "Mordeduras en media luna en el borde de las hojas (adulto); larvas comen raíces y corteza "
        "del cuello: la planta se marchita y se suelta del suelo.",
        "Otiorhynchus rugosostriatus (café rojizo, sin manchas amarillas).", "plaga"),
    _sp(P, "Burrito de la frutilla", "Otiorhynchus rugosostriatus", "FAC",
        "Gorgojo café rojizo oscuro de 7–8 mm, élitros con hileras de puntos rugosos; no vuela.",
        "Larva blanca ápoda en raíces; adulto nocturno.",
        "Como O. sulcatus: hojas mordidas en el borde y raíces comidas.",
        "Otiorhynchus sulcatus (negro con manchitas amarillas).", "plaga"),
    # --- Escarabajos de suelo (pololos, gusanos blancos)
    _sp(P, "Pololo (Sericoides)", "Sericoides spp.", "FAC",
        "Escarabajo chico (8–12 mm), café a café rojizo, ovalado, algo aterciopelado; antenas "
        "terminadas en laminillas. Vuela al atardecer.",
        "Larva gusano blanco en «C» con 3 pares de patas y cabeza café (distinto al gorgojo, que no "
        "tiene patas). Ciclo de 1–2 años en el suelo.",
        "Larvas comen raíces (en cranberry, raíces y guías bajo el musgo: manchones secos); adultos "
        "comen hojas y brotes en la noche.",
        "Hylamorpha elegans (adulto verde metálico), Phytoloema herrmanni.", "plaga", "género"),
    _sp(P, "Gusano blanco", "Hylamorpha elegans", "FAC",
        "Adulto: pololo verde brillante a verde café (15–20 mm). Larva: gusano blanco grueso en «C», "
        "con patas y cabeza café-anaranjada.",
        "Huevo blanco en el suelo; larva 3 estadios (la más grande daña más); pupa en el suelo; "
        "adultos en vuelo en noviembre–diciembre.",
        "Larvas cortan raíces: plantas débiles que se sueltan; en praderas vecinas suele haber mucho.",
        "Sericoides (adulto café, más chico), larvas de gorgojo (sin patas).", "plaga"),
    _sp(P, "Pololo café", "Phytoloema herrmanni", "FA",
        "Escarabajo café claro de 12–15 mm, con pelos en el tórax; vuela al atardecer en primavera.",
        "Larva gusano blanco con patas, en el suelo.", "Larvas en raíces; adultos en hojas.",
        "Hylamorpha elegans (verde).", "plaga"),
    # --- Moscas y polillas de fruta y brote
    _sp(P, "Drosophila de alas manchadas", "Drosophila suzukii", "FAC",
        "Mosquita de 2–3 mm, ojos rojos, cuerpo amarillo café. El macho tiene una mancha oscura en "
        "la punta de cada ala; la hembra, un ovipositor aserrado grande (sin manchas en las alas).",
        "Huevo dentro de la fruta sana (dos filamentos blancos asoman por el orificio); larva blanca "
        "sin patas dentro de la fruta; pupa café en la fruta o el suelo.",
        "Fruta madura que se ablanda, se hunde y gotea; larvas al apretarla o en prueba de sal/azúcar.",
        "Drosophila melanogaster y otras (solo en fruta podrida; macho sin manchas).", "plaga"),
    _sp(P, "Polilla de la fruta", "Proeulia auraria", "FAC",
        "Polilla (Tortricidae) de 15–20 mm de envergadura, alas anteriores café dorado con dibujos "
        "más oscuros; en reposo forma una campana.",
        "Larva verde amarillenta con cabeza café, muy activa (se retuerce y cae colgando de un hilo); "
        "pupa café dentro de hojas enrolladas.",
        "Hojas y brotes unidos con seda; larvas comen fruta y la contaminan (problema cuarentenario).",
        "Proeulia chrysopteris, otros enrolladores (Chileulia).", "plaga"),
    _sp(P, "Enrollador de hojas", "Tortricidae", "FAC",
        "Polillas pequeñas con alas en forma de campana; larvas verdes que enrollan hojas con seda.",
        "Larva que se mueve hacia atrás al tocarla; pupa en la hoja enrollada.",
        "Hojas enrolladas y brotes atados; daño en fruta.", "Proeulia auraria (identificar la especie).",
        "plaga", "familia"),
    # --- Chupadores
    _sp(P, "Pulgón grande del frambueso", "Amphorophora idaei", "F",
        "Pulgón grande (3–4 mm), verde claro brillante, patas y antenas largas; sifones largos.",
        "Ninfas más chicas del mismo color; adultos ápteros y alados en colonias en el envés de hojas "
        "nuevas.", "Transmite virus (mosaico del frambueso); poco daño directo.",
        "Otros pulgones (más chicos, colonias densas).", "plaga"),
    _sp(P, "Pulgones", "Aphididae", "FAC",
        "Insectos blandos de 1–3 mm, en forma de pera, con dos sifones (tubitos) atrás; verdes, negros "
        "o grises; en colonias.",
        "Ninfas, adultos sin alas y alados; mudas blancas alrededor de la colonia.",
        "Brotes enrollados, mielecilla, fumagina (hollín negro); transmiten virus.",
        "Trips (alargados, sin sifones), chanchitos (con cera blanca).", "plaga", "familia"),
    _sp(P, "Trips", "Frankliniella spp.", "FAC",
        "Insectos alargados de 1–2 mm, amarillos a cafés, alas con flecos; dentro de flores.",
        "Larvas amarillo claro sin alas; adultos alados.",
        "Flores y frutos con manchas plateadas o deformes; drupéolas secas.",
        "Pulgones (más gordos, con sifones).", "plaga", "género"),
    _sp(P, "Arañita roja (ácaro)", "Tetranychus urticae", "FAC",
        "Ácaro de 0,5 mm, verde amarillento con dos manchas oscuras (en otoño rojo anaranjado); 8 "
        "patas; telaraña fina en el envés.",
        "Huevos esféricos traslúcidos; larva con 6 patas; ninfas y adultos con 8.",
        "Hojas punteadas, amarillas o bronceadas, con telaraña; caída de hojas en verano seco.",
        "Ácaros depredadores (más rápidos, en forma de pera, sin manchas).", "plaga"),
    _sp(P, "Eriófido del frambueso", "Phyllocoptes gracilis", "F",
        "Ácaro microscópico (0,15 mm), alargado como gusano, solo visible con lupa de 20×.",
        "Todo el ciclo en el envés de hojas y yemas.",
        "Manchas amarillas en el haz de la hoja y frutos deformes, con drupéolas secas.",
        "Virosis (patrón de mosaico), daño de trips.", "plaga"),
    _sp(P, "Chanchito blanco", "Pseudococcus spp.", "AF",
        "Insecto ovalado de 3–4 mm cubierto de cera blanca, con filamentos de cera alrededor; "
        "en grietas, bajo la corteza y en racimos.",
        "Huevos en un saco algodonoso; ninfas móviles (migratorias) rosadas o amarillas; adultos.",
        "Mielecilla y fumagina; contaminación de fruta (cuarentenario).",
        "Escamas (sin cera algodonosa), pulgones.", "plaga", "género"),
    _sp(P, "Escamas", "Coccoidea", "AF",
        "Escudos inmóviles (1–3 mm), redondos u ovalados, grises, cafés o blancos, pegados a la "
        "corteza, hojas o frutos.",
        "Ninfa móvil (crawler) amarilla pequeña; luego se fija y forma su escudo.",
        "Ramas debilitadas, manchas en frutos; algunas son cuarentenarias en arándano.",
        "Chanchito blanco (con cera algodonosa, se mueve).", "plaga", "grupo"),
    _sp(P, "Chinches", "Miridae", "FA",
        "Chinches de 4–7 mm, verdes o cafés, alas con una parte dura y otra membranosa, antenas "
        "largas; muy rápidos.", "Ninfas sin alas, del mismo color.",
        "Picaduras en brotes y frutos: drupéolas deformes o frutos con manchas.",
        "Trips (mucho más chicos).", "plaga", "familia"),
    _sp(P, "Babosas", "Deroceras reticulatum", "FAC",
        "Molusco sin concha, gris o crema con manchas oscuras en red, 3–5 cm; deja rastro de baba.",
        "Huevos en racimos de perlas traslúcidas en el suelo húmedo; juveniles iguales pero chicos.",
        "Hojas y frutos comidos con agujeros irregulares y baba seca brillante.",
        "Caracol (con concha).", "plaga"),
    _sp(P, "Caracol de jardín", "Cornu aspersum", "FAC",
        "Caracol con concha globosa café con bandas oscuras, 25–35 mm.",
        "Huevos blancos en el suelo; juveniles de concha frágil.",
        "Hojas y frutos comidos; baba; contaminación de fruta.", "Babosas (sin concha).", "plaga"),
    # --- Benéficos y polinizadores
    _sp(P, "Chinita", "Coccinellidae", "FAC",
        "Escarabajos redondos de 2–8 mm, rojos, anaranjados o negros con puntos; patas cortas.",
        "Huevos amarillos en grupos; larva alargada gris oscuro con manchas naranjas (como "
        "lagartija); pupa pegada a la hoja.",
        "Benéfica: comen pulgones, escamas y ácaros.", "Larva confundible con plaga: NO eliminar.",
        "benefico", "familia"),
    _sp(P, "Crisopa", "Chrysoperla spp.", "FAC",
        "Insecto verde claro de 10–15 mm, alas grandes transparentes con venas verdes, ojos dorados.",
        "Huevo blanco sobre un pedicelo largo (hilo); larva café con mandíbulas en tenaza; capullo "
        "blanco redondo.", "Benéfica: larvas comen pulgones, trips, huevos y larvas.",
        "Larva parecida a chinita (la crisopa tiene tenazas).", "benefico", "género"),
    _sp(P, "Sírfidos (moscas de las flores)", "Syrphidae", "FAC",
        "Moscas con franjas amarillas y negras (parecen avispas) que se quedan suspendidas en el aire.",
        "Larva verde o café, sin patas, como babosa pequeña dentro de colonias de pulgón.",
        "Benéficos: larvas comen pulgones; adultos polinizan.", "Avispas (cintura fina, 4 alas).",
        "benefico", "familia"),
    _sp(P, "Ácaros depredadores", "Phytoseiidae", "FAC",
        "Ácaros en forma de pera, brillantes, rojo claro a crema, muy rápidos; sin manchas.",
        "Huevos ovalados; ninfas y adultos similares.", "Benéficos: comen arañita roja y trips.",
        "Arañita roja (lenta, con dos manchas, telaraña).", "benefico", "familia"),
    _sp(P, "Avispitas parasitoides", "Aphidiinae", "FAC",
        "Avispas diminutas (2–3 mm), negras, cintura fina; se ven sobre las colonias de pulgón.",
        "Pulgón «momia»: inflado, color café dorado o gris, con un agujero redondo de salida.",
        "Benéficas: parasitan pulgones.", "Pulgones muertos por hongos (cubiertos de pelusa).",
        "benefico", "grupo"),
    _sp(P, "Abejorro", "Bombus spp.", "FAC",
        "Abejas grandes y peludas, negras con bandas amarillas o blancas (B. terrestris) o "
        "anaranjadas (B. dahlbomii, nativo).", "Colonias en el suelo; obreras de tamaño variable.",
        "Polinizadores (clave en arándano).", "Abeja de miel (más chica y menos peluda).",
        "benefico", "género"),
    _sp(P, "Abeja de miel", "Apis mellifera", "FAC",
        "Abeja de 12–15 mm, café dorada con bandas oscuras, poco pelo; cestas de polen en patas.",
        "Obrera, zángano (grande, ojos grandes) y reina.", "Polinizadora.",
        "Moscas sírfidas (2 alas, sin cintura).", "benefico"),
    # ================================================================== MALEZAS
    _sp(M, "Vinagrillo", "Rumex acetosella", "FAC",
        "Hojas pequeñas en forma de punta de flecha (con dos orejitas en la base), sabor ácido; "
        "tallos rojizos; flores rojizas en espiga; rizomas rastreros. Típica de suelos ácidos.",
        "Roseta de hojas lanceoladas; luego tallos florales de 20–40 cm rojizos.",
        "Compite y se propaga por rizomas: forma manchones, muy común en arándano y cranberry.",
        "Romaza (mucho más grande), Oxalis (hojas de trébol).", rank="especie"),
    _sp(M, "Romaza", "Rumex spp.", "FA",
        "Hojas grandes (20–30 cm) lanceoladas u ovaladas, borde ondulado (R. crispus) o anchas con "
        "base acorazonada (R. obtusifolius); raíz pivotante gruesa amarilla; panículas de semillas "
        "café rojizas.", "Roseta grande; tallo floral de 60–120 cm; semillas aladas cafés.",
        "Muy competitiva, rebrota desde la raíz.", "Vinagrillo (chica, con orejitas).", rank="género"),
    _sp(M, "Diente de león", "Taraxacum officinale", "FAC",
        "Roseta con hojas profundamente dentadas (dientes hacia la base), látex blanco; flor "
        "amarilla solitaria en tallo hueco; vilano blanco esférico.",
        "Plántula con hojas ovaladas; roseta; flor; «globo» de semillas.",
        "Compite y hospeda plagas; raíz pivotante que rebrota.",
        "Hierba del chancho (hojas con pelos ásperos, tallos ramificados).", rank="especie"),
    _sp(M, "Hierba del chancho", "Hypochaeris radicata", "FAC",
        "Roseta de hojas lobuladas con pelos ásperos; tallos florales ramificados, sin hojas, con "
        "varias flores amarillas.", "Roseta perenne; floración de primavera a otoño.",
        "Muy común en praderas y entre hileras.", "Diente de león (tallo no ramificado, hoja lisa).",
        rank="especie"),
    _sp(M, "Siete venas", "Plantago lanceolata", "FAC",
        "Hojas lanceoladas en roseta con 3–7 nervaduras paralelas muy marcadas; espiga floral "
        "oscura y corta en un tallo largo con surcos.", "Roseta; espigas con anteras blancas.",
        "Compite en entre hileras.", "Llantén (hoja ancha ovalada).", rank="especie"),
    _sp(M, "Llantén", "Plantago major", "FAC",
        "Hojas anchas ovaladas en roseta, nervaduras paralelas, pecíolo ancho; espigas largas y "
        "delgadas verdes.", "Roseta; espigas.", "Resiste pisoteo: caminos y cabeceras.",
        "Siete venas (hoja angosta).", rank="especie"),
    _sp(M, "Trébol blanco", "Trifolium repens", "FAC",
        "Hojas de 3 folíolos redondeados, a menudo con una «V» blanca; estolones rastreros que "
        "enraízan; cabezuelas blancas.", "Plántula con cotiledones ovalados; estolones; flores.",
        "Cubre el suelo entre plantas; en cranberry compite con las guías.",
        "Oxalis (folíolos acorazonados, sin estolones enraizados), lotera.", rank="especie"),
    _sp(M, "Botón de oro", "Ranunculus repens", "FAC",
        "Hojas divididas en 3 segmentos dentados, a menudo con manchas claras; estolones; flores "
        "amarillo brillante (5 pétalos lustrosos). Suelos húmedos.",
        "Roseta con estolones que enraízan; floración en primavera.",
        "Forma manchones en sectores húmedos (cranberry, bajos).", "Potentilla, trébol.",
        rank="especie"),
    _sp(M, "Pasto miel", "Holcus lanatus", "FAC",
        "Gramínea perenne gris verdosa muy peluda y suave al tacto; vainas con rayas rosadas o "
        "moradas; panoja blanquecina a rosada.", "Macollos; espigado en primavera–verano.",
        "Muy común en el sur; compite y se instala en la hilera.", "Ballica (lisa, brillante).",
        rank="especie"),
    _sp(M, "Chépica", "Agrostis capillaris", "FAC",
        "Gramínea fina, perenne, con rizomas/estolones; lígula corta; panoja abierta, fina y "
        "rojiza.", "Césped denso que se extiende.",
        "Invade la hilera y en cranberry se mete entre las guías.",
        "Chépica alemana (rizomas blancos gruesos), Poa annua.", rank="especie"),
    _sp(M, "Chépica alemana", "Elymus repens", "FA",
        "Gramínea con rizomas blancos, largos y puntudos; hojas planas con aurículas que abrazan el "
        "tallo; espiga delgada tipo trigo.", "Rebrota desde trozos de rizoma.",
        "Muy difícil de controlar, se propaga con labores.", "Chépica (fina, sin aurículas).",
        rank="especie"),
    _sp(M, "Ballica", "Lolium spp.", "FAC",
        "Gramínea de hojas brillantes por el envés, base de los tallos rojiza; espiga plana con "
        "espiguillas alternas pegadas al eje.", "Macollos; espigado en primavera.",
        "Compite por agua y nitrógeno.", "Pasto miel (peludo), pasto ovillo (aplanado, panoja densa).",
        rank="género"),
    _sp(M, "Pasto ovillo", "Dactylis glomerata", "FA",
        "Gramínea en champas, tallos aplanados en la base, hojas azulverdosas; panoja con "
        "espiguillas en ovillos densos.", "Champa perenne.", "Compite en entre hileras.",
        "Ballica (espiga plana).", rank="especie"),
    _sp(M, "Pasto cebolla", "Arrhenatherum elatius", "FA",
        "Gramínea alta con bulbitos en la base (como cebollitas en cadena); panoja brillante con "
        "aristas.", "Rebrota desde los bulbitos.", "Difícil de controlar: los bulbitos se dispersan.",
        "Pasto miel.", rank="especie"),
    _sp(M, "Pasto oloroso", "Anthoxanthum odoratum", "FAC",
        "Gramínea baja con olor a pasto recién cortado (cumarina); espiga corta y densa amarilla "
        "verdosa que florece temprano.", "Champas pequeñas.", "Común en suelos ácidos y pobres.",
        "Pasto miel.", rank="especie"),
    _sp(M, "Poa", "Poa annua", "FAC",
        "Gramínea baja, verde claro, hojas con punta en «proa de bote»; panoja triangular chica; "
        "florece casi todo el año.", "Anual o de vida corta; semilla abundante.",
        "Cubre el suelo húmedo y cabeceras.", "Chépica (perenne, panoja rojiza).", rank="especie"),
    _sp(M, "Quilloi-quilloi", "Stellaria media", "FAC",
        "Planta rastrera tierna, hojas ovaladas opuestas, una línea de pelos en el tallo; flores "
        "blancas chicas con 5 pétalos partidos (parecen 10).", "Anual de invierno; plántula muy temprana.",
        "Cubre el suelo en invierno–primavera.", "Cerastium (peludo).", rank="especie"),
    _sp(M, "Senecio", "Senecio vulgaris", "FA",
        "Hojas lobuladas irregulares algo carnosas; flores amarillas en cabezuelas cilíndricas sin "
        "pétalos (rayos), con puntas negras en las brácteas.", "Anual, varias generaciones al año.",
        "Hospeda plagas y enfermedades; semilla muy abundante.", "Ñilhue.", rank="especie"),
    _sp(M, "Ñilhue", "Sonchus spp.", "FAC",
        "Hojas lobuladas que abrazan el tallo, a veces con espinitas en el borde; látex blanco; "
        "tallo hueco; cabezuelas amarillas pálidas.", "Roseta y luego tallo de 30–100 cm.",
        "Compite; hospeda pulgones.", "Diente de león (sin tallo con hojas).", rank="género"),
    _sp(M, "Bolsita del pastor", "Capsella bursa-pastoris", "FA",
        "Roseta de hojas dentadas; tallo con flores blancas chicas; frutos triangulares en forma de "
        "corazón (bolsita).", "Anual; florece casi todo el año.", "Hospeda plagas.",
        "Rábano silvestre (más grande, fruto alargado).", rank="especie"),
    _sp(M, "Pasto pinito", "Spergula arvensis", "FA",
        "Hojas filiformes en verticilos (parecen agujas de pino) en los nudos; flores blancas "
        "pequeñas; suelos ácidos arenosos.", "Anual.", "Cubre el suelo en primavera.",
        "Galium (hojas más anchas, tallo áspero).", rank="especie"),
    _sp(M, "Sanguinaria", "Polygonum aviculare", "FA",
        "Rastrera, tallos con nudos envainados por una membrana plateada (ócrea); hojas pequeñas "
        "elípticas; flores diminutas blancas o rosadas en las axilas.", "Anual de primavera–verano.",
        "Común en caminos y suelo compactado.", "Duraznillo (erguido, hojas más grandes).",
        rank="especie"),
    _sp(M, "Duraznillo", "Persicaria maculosa", "FA",
        "Hojas lanceoladas con una mancha oscura en el centro; tallo con nudos rojizos y ócrea; "
        "espigas densas rosadas.", "Anual de verano.", "Compite en sectores húmedos.",
        "Sanguinaria (rastrera).", rank="especie"),
    _sp(M, "Quinguilla", "Chenopodium album", "FA",
        "Hojas romboidales con borde dentado, cubiertas de polvillo blanco harinoso (sobre todo las "
        "nuevas); flores verdes en glomérulos.", "Anual de verano; muy alta (1 m).",
        "Compite en plantaciones nuevas.", "Atriplex.", rank="especie"),
    _sp(M, "Lengua de gato", "Galium aparine", "FA",
        "Trepadora con tallos cuadrados ásperos (se pegan a la ropa) y hojas en verticilos de 6–8; "
        "frutos redondos con ganchitos.", "Anual de invierno–primavera.",
        "Trepa sobre las cañas y dificulta la cosecha.", "Pasto pinito (hojas filiformes).",
        rank="especie"),
    _sp(M, "Correhuela", "Convolvulus arvensis", "FA",
        "Enredadera perenne de hojas en forma de flecha; flores en embudo blancas o rosadas de "
        "2–3 cm; raíces profundas.", "Rebrota desde raíces y rizomas.",
        "Se enreda en las plantas; muy difícil de erradicar.",
        "Correhuela grande (flor blanca de 5–7 cm).", rank="especie"),
    _sp(M, "Correhuela grande", "Calystegia sepium", "FAC",
        "Enredadera de hojas grandes acorazonadas a sagitadas; flores blancas grandes (5–7 cm) en "
        "embudo; rizomas blancos carnosos. Sectores húmedos.", "Rebrota desde rizomas en primavera.",
        "Cubre las plantas y quita luz.", "Correhuela (flor chica).", rank="especie"),
    _sp(M, "Cardo negro", "Cirsium vulgare", "FA",
        "Roseta de hojas muy espinosas, con pelos ásperos arriba; tallo alado espinoso; cabezuelas "
        "moradas grandes.", "Bianual: roseta el primer año, flor el segundo.", "Molesta la cosecha.",
        "Cardo (Cirsium arvense, rizomatoso, flores chicas).", rank="especie"),
    _sp(M, "Cardo", "Cirsium arvense", "FA",
        "Perenne con rizomas que forma manchones; hojas onduladas espinosas, sin pelos ásperos; "
        "cabezuelas lilas pequeñas.", "Rebrota desde rizomas.", "Muy invasor.",
        "Cardo negro (bianual, sin rizomas).", rank="especie"),
    _sp(M, "Zarzamora", "Rubus ulmifolius", "FAC",
        "Arbusto con tallos arqueados muy espinosos; hojas de 3–5 folíolos, blanquecinas por debajo; "
        "flores rosadas; mora negra.", "Brota de raíz y las puntas de los tallos enraízan.",
        "Invade bordes y hospeda plagas y enfermedades del frambueso.",
        "Frambueso (fruto rojo que se desprende hueco).", rank="especie"),
    _sp(M, "Espinillo (tojo)", "Ulex europaeus", "FAC",
        "Arbusto muy espinoso verde oscuro (las hojas son espinas); flores amarillas como arveja; "
        "vainas negras que explotan.", "Plántula con hojas de 3 folíolos; luego espinas.",
        "Invasor agresivo en bordes y suelos ácidos.", "Retamilla (sin espinas).", rank="especie"),
    _sp(M, "Retamilla", "Cytisus scoparius", "FA",
        "Arbusto de tallos verdes angulosos casi sin hojas, sin espinas; flores amarillas grandes "
        "tipo arveja.", "Perenne; semillas duraderas en el suelo.", "Invade bordes.",
        "Espinillo (espinoso).", rank="especie"),
    _sp(M, "Junquillo", "Juncus spp.", "FAC",
        "Tallos cilíndricos lisos, sin nudos, verde oscuro, en champas; flores cafés en un grupo "
        "lateral. Suelos saturados.", "Champas perennes.",
        "Indica mal drenaje; muy común en cranberry y bajos.", "Cyperáceas (tallo triangular).",
        rank="género"),
    _sp(M, "Cyperáceas (cortadera, carex)", "Cyperaceae", "C",
        "Plantas tipo pasto pero de tallo triangular (al rodarlo entre los dedos se sienten las "
        "aristas), sin nudos; hojas en tres filas.", "Perennes con rizomas.",
        "Compiten en sectores húmedos de cranberry.", "Junquillo (tallo cilíndrico), gramíneas "
        "(tallo redondo con nudos).", rank="familia"),
    _sp(M, "Cola de caballo", "Equisetum spp.", "FAC",
        "Tallos huecos articulados con verticilos de ramitas finas (parece pino chico); sin flores; "
        "en primavera tallos cafés con un cono de esporas.", "Rebrota desde rizomas profundos.",
        "Indica humedad; difícil de controlar en cranberry.", "Pasto pinito (con flores blancas).",
        rank="género"),
    _sp(M, "Hidrocótile (sombrerito de agua)", "Hydrocotyle spp.", "C",
        "Rastrera de hojas redondas brillantes con el pecíolo al centro (como sombrilla); estolones "
        "finos que enraízan. Suelos muy húmedos.", "Perenne.",
        "Cubre la cama de cranberry entre las guías.", "Trébol (3 folíolos).", rank="género"),
    _sp(M, "Lotera", "Lotus pedunculatus", "FAC",
        "Hojas de 5 folíolos (3 arriba y 2 abajo pegados al tallo); flores amarillas en umbela; "
        "tallos huecos; rizomas. Suelos húmedos.", "Perenne.", "Se mete en la hilera y en cranberry.",
        "Trébol (3 folíolos).", rank="especie"),
    _sp(M, "Hierba mora", "Prunella vulgaris", "FAC",
        "Tallos cuadrados rastreros; hojas opuestas ovaladas; espiga corta y densa de flores "
        "moradas.", "Perenne, forma manchones.", "Cubre el suelo húmedo.", "Menta.", rank="especie"),
    _sp(M, "Margarita", "Leucanthemum vulgare", "FA",
        "Roseta de hojas dentadas en forma de cuchara; flores tipo margarita blancas con centro "
        "amarillo de 3–5 cm.", "Perenne.", "Compite en bordes.", "Manzanilla (hojas muy finas).",
        rank="especie"),
    _sp(M, "Milenrama", "Achillea millefolium", "FA",
        "Hojas muy divididas, plumosas y aromáticas; flores blancas a rosadas en corimbo plano.",
        "Perenne con rizomas.", "Forma manchones.", "Manzanilla (flor con centro amarillo grande).",
        rank="especie"),
    _sp(M, "Dedalera", "Digitalis purpurea", "FA",
        "Roseta de hojas grandes, aterciopeladas, verde grisáceo; espiga alta con flores rosado "
        "morado en forma de dedal. Tóxica.", "Bianual.", "Invade bordes y plantaciones nuevas.",
        "Gordolobo (hojas más lanudas, flor amarilla).", rank="especie"),
    _sp(M, "Rábano silvestre", "Raphanus raphanistrum", "FA",
        "Hojas lobuladas ásperas (la terminal más grande); flores de 4 pétalos amarillo pálido, "
        "blancas o lilas con venas; fruto alargado con estrangulaciones.", "Anual.",
        "Compite en plantaciones nuevas.", "Yuyo (Brassica, flores amarillo intenso, hojas que "
        "abrazan el tallo).", rank="especie"),
    _sp(M, "Yuyo", "Brassica rapa", "FA",
        "Hojas inferiores lobuladas y las superiores abrazando el tallo; flores amarillo intenso de "
        "4 pétalos; silicuas largas.", "Anual de invierno–primavera.", "Compite y hospeda plagas.",
        "Rábano silvestre.", rank="especie"),
    _sp(M, "Malva", "Malva spp.", "FA",
        "Hojas redondas con 5–7 lóbulos suaves y borde dentado, pecíolo largo; flores rosado pálido "
        "de 5 pétalos; fruto en forma de queso.", "Anual o bianual; raíz pivotante.",
        "Compite y hospeda arañita.", "Geranio silvestre (hojas más divididas).", rank="género"),
    _sp(M, "Verónica", "Veronica persica", "FA",
        "Rastrera con hojas ovaladas dentadas peludas; flores azules de 4 pétalos con el inferior "
        "más claro.", "Anual de invierno.", "Cubre el suelo.", "Quilloi-quilloi (flor blanca).",
        rank="especie"),
    _sp(M, "Sanguinaria de hoja ancha (Oxalis)", "Oxalis spp.", "FAC",
        "Hojas de 3 folíolos acorazonados (como trébol pero con un pliegue al centro), sabor ácido; "
        "flores amarillas o rosadas de 5 pétalos.", "Perenne con bulbillos o rizomas.",
        "Difícil de eliminar: bulbillos.", "Trébol (folíolos redondos con «V» blanca).",
        rank="género"),
    _sp(M, "Chufa", "Cyperus spp.", "FA",
        "Tallo triangular, hojas brillantes en tres filas; espiguillas doradas; tubérculos chicos.",
        "Rebrota desde tubérculos.", "Muy difícil de controlar.", "Gramíneas (tallo redondo).",
        rank="género"),
    _sp(M, "Maicillo", "Sorghum halepense", "FA",
        "Gramínea alta de hojas anchas con nervadura central blanca; rizomas gruesos; panoja rojiza.",
        "Rebrota desde rizomas.", "Muy invasora (poco común en el sur lluvioso).",
        "Chépica alemana.", rank="especie"),
    # ================================================================== ENFERMEDADES
    _sp(E, "Botritis (pudrición gris)", "Botrytis cinerea", "FAC",
        "Fruta blanda café que se cubre de un moho gris polvoriento (esporas); en flores, pétalos "
        "cafés pegados; en cañas, manchas café claro con anillos.",
        "Síntoma inicial: mancha acuosa en fruta o flor. Avanzado: fruta momificada. Signo: moho "
        "gris aterciopelado que suelta polvo al tocarlo.",
        "Principal pudrición de fruta en el sur lluvioso; también tizón de flores (cranberry).",
        "Rhizopus (moho negro con pelos largos), Penicillium (verde azulado).", rank="especie"),
    _sp(E, "Oídio", "Podosphaera spp.", "FA",
        "Polvillo blanco como harina sobre hojas, brotes y frutos (se borra con el dedo); hojas "
        "enrolladas hacia arriba.", "Manchas blancas aisladas → cubre toda la hoja → puntitos negros "
        "(cleistotecios) a fin de temporada.", "Frutos opacos y deformes; brotes débiles.",
        "Residuo de pesticida, polvo.", rank="género"),
    _sp(E, "Roya", "Phragmidium rubi-idaei", "F",
        "Pústulas amarillo anaranjadas en el envés de las hojas (polvillo naranja al tocarlas); "
        "manchas amarillas en el haz; en otoño, pústulas negras.",
        "Primavera: pústulas naranjas en hojas nuevas; verano: amarillas; otoño: negras.",
        "Defoliación anticipada.", "Daño de eriófido (sin polvillo).", rank="especie"),
    _sp(E, "Tizón de la caña", "Didymella applanata", "F",
        "Manchas púrpura a café en las cañas alrededor de las yemas (base de la hoja), que se vuelven "
        "gris plateado con puntitos negros.", "Mancha morada en verano → gris plateada en invierno.",
        "Yemas que no brotan o laterales débiles.", "Cancro de la caña, antracnosis.", rank="especie"),
    _sp(E, "Cancro de la caña", "Paraconiothyrium fuckelii", "FA",
        "Cancro café oscuro a púrpura que parte en heridas o cortes de poda y avanza por la caña; "
        "puntitos negros (picnidios).", "Lesión en la herida → cancro que anilla → caña muerta.",
        "Cañas o ramas que se secan.", "Tizón de la caña (parte en las yemas).", rank="especie"),
    _sp(E, "Antracnosis", "Elsinoë veneta", "F",
        "Manchas pequeñas redondas en las cañas, centro gris claro hundido y borde morado; en hojas, "
        "manchitas con centro que se cae (perdigonado).", "Mancha morada → centro gris hundido.",
        "Cañas agrietadas; frutos secos.", "Tizón de la caña.", rank="especie"),
    _sp(E, "Pudrición de raíz", "Phytophthora spp.", "FAC",
        "Plantas que amarillean, se marchitan y mueren en sectores bajos o mal drenados; raíces "
        "café rojizas sin raicillas; la corteza del cuello se desprende y por dentro está café rojiza "
        "(sano: blanco).", "Hojas amarillas o rojizas → marchitez → muerte; avanza en manchones.",
        "Pérdida de plantas; P. rubi en frambuesa, P. cinnamomi en arándano y cranberry.",
        "Daño de larvas en raíces (raíces comidas, no podridas), asfixia, sequía.", rank="género"),
    _sp(E, "Cancro bacteriano", "Pseudomonas syringae", "FA",
        "Brotes y yemas negras después de heladas en primavera; lesiones café negras en tallos, sin "
        "puntitos negros; en arándano, ramillas con cancros rojizos a negros.",
        "Yemas negras → brote quemado (pastor) → cancro.",
        "Muy ligado a heladas y lluvias en brotación.", "Daño por helada (sin avance), cancros "
        "fúngicos (con puntitos negros).", rank="especie"),
    _sp(E, "Agalla del cuello", "Agrobacterium tumefaciens", "FA",
        "Tumores redondeados rugosos en el cuello, raíces o cañas, blandos y blancos al inicio, luego "
        "duros, cafés y agrietados.", "Agalla pequeña lisa → grande y leñosa.",
        "Plantas débiles.", "Callo de herida (liso, no crece).", rank="especie"),
    _sp(E, "Verticilosis", "Verticillium spp.", "F",
        "Hojas de la base que amarillean y se secan por un lado de la caña; vasos de la caña con "
        "rayas café azuladas al cortarla.", "Marchitez parcial → caña seca.", "Muerte de cañas.",
        "Phytophthora (pudre raíz).", rank="género"),
    _sp(E, "Cancro del arándano (Botryosphaeria)", "Botryosphaeriaceae", "A",
        "Ramas o brotes que se secan bruscamente con hojas cafés pegadas; cancro café rojizo que "
        "avanza desde heridas o cortes de poda; al cortar, madera café en forma de cuña.",
        "Brote seco → cancro → muerte de la rama.",
        "Muerte regresiva de ramas (Neofusicoccum, Lasiodiplodia).",
        "Phomopsis, Pestalotiopsis, Pseudomonas.", rank="familia"),
    _sp(E, "Pestalotiopsis", "Neopestalotiopsis spp.", "A",
        "Lesiones café en tallos y hojas con pústulas negras (acérvulos) que liberan esporas como "
        "tinta; muerte de ramillas.", "Mancha café → pústulas negras.", "Cancro y muerte de ramillas.",
        "Botryosphaeria.", rank="género"),
    _sp(E, "Tizón de ramillas (Phomopsis)", "Diaporthe vaccinii", "AC",
        "Puntas de ramillas que se secan desde arriba con lesión café rojiza; en cranberry, ramillas "
        "erguidas (uprights) que se ponen color bronce y mueren.",
        "Puntas secas → ramilla muerta; pudrición de fruta en cosecha.",
        "Muerte de ramillas (upright dieback) y pudrición de fruta.", "Daño por helada, Botryosphaeria.",
        rank="especie"),
    _sp(E, "Antracnosis del arándano", "Colletotrichum spp.", "AC",
        "Fruta madura que se hunde cerca del cáliz y se cubre de masas de esporas naranjas o "
        "salmón; en hojas, manchas cafés.", "Mancha hundida → masas naranjas.",
        "Pudrición de fruta (en cranberry, parte del complejo de pudrición).",
        "Botritis (moho gris), Alternaria (moho verde oscuro).", rank="género"),
    _sp(E, "Alternaria", "Alternaria spp.", "A",
        "Fruta con pudrición blanda cubierta de moho verde oliva oscuro cerca del cáliz o de grietas.",
        "Mancha → moho oscuro.", "Pudrición de postcosecha.", "Colletotrichum (esporas naranjas).",
        rank="género"),
    _sp(E, "Pudrición de fruta del cranberry", "Complejo de hongos", "C",
        "Bayas blandas, descoloridas, con manchas claras o hundidas, que se arrugan; puede haber "
        "puntitos negros. Causado por varios hongos (Colletotrichum, Coleophoma, Physalospora, "
        "Phyllosticta, Phomopsis, Botrytis).", "Mancha en la baya → baya blanda → momia.",
        "Pérdida de fruta en campo y almacenaje.", "Daño de sol (sin pudrición), helada.",
        rank="grupo"),
    _sp(E, "Mancha roja de la hoja", "Exobasidium rostrupii", "C",
        "Manchas redondas rojo intenso en el haz de las hojas nuevas; por debajo, capa blanca de "
        "esporas.", "Mancha roja → envés blanco → hoja que cae.", "Defoliación.",
        "Coloración otoñal (uniforme, sin capa blanca).", rank="especie"),
    _sp(E, "Moho azul (postcosecha)", "Penicillium spp.", "FAC",
        "Fruta blanda con moho azul verdoso polvoriento, borde blanco.", "Mancha → moho azul.",
        "Pudrición en almacenaje.", "Botritis (gris).", rank="género"),
    _sp(E, "Rhizopus", "Rhizopus stolonifer", "FA",
        "Fruta muy blanda que se deshace y gotea, cubierta de pelos blancos largos con cabecitas "
        "negras.", "Rápido en calor.", "Pudrición de postcosecha.", "Botritis (polvo gris).",
        rank="especie"),
    _sp(E, "Virosis", "virus", "FAC",
        "Mosaicos (manchas verde claro y oscuro), venas amarillas, hojas deformes o enanismo; en "
        "frambuesa, fruta que se desgrana (RBDV).", "Síntomas que no avanzan como mancha; plantas "
        "enteras afectadas.", "Plantas improductivas; se transmiten por pulgones, nematodos, polen "
        "o material de propagación.", "Deficiencias nutricionales, daño de herbicida, eriófidos.",
        rank="grupo"),
    _sp(E, "Daño por helada", "Abiótico", "FAC",
        "Flores con el centro negro; brotes nuevos negros y caídos de un día para otro, en las partes "
        "bajas o expuestas.", "Daño parejo después de una noche fría; no avanza.",
        "Pérdida de flores y brotes.", "Pseudomonas (cancros que avanzan).", rank="grupo"),
    _sp(E, "Clorosis (deficiencia)", "Abiótico", "FAC",
        "Hojas amarillas con venas verdes (fierro/manganeso, en hojas nuevas; típico de pH alto en "
        "arándano y cranberry) o amarillo parejo en hojas viejas (nitrógeno); bordes rojizos "
        "(fósforo, magnesio).", "Patrón parejo en la planta según la edad de la hoja.",
        "Menor crecimiento.", "Virosis (mosaico irregular), daño de raíz.", rank="grupo"),
]

# Cómo sacar las fotos para que la IA reconozca mejor (por sección).
PHOTO_GUIDE = {
    "_": [
        "Enfoque nítido: toque la pantalla sobre el bicho, la hoja o la lesión antes de disparar.",
        "Luz pareja: sombra suave o día nublado; evite el sol directo con sombras duras y el flash.",
        "Llénela: el objeto debe ocupar buena parte de la foto (acérquese o use zoom 2×).",
        "Fondo simple: una hoja, la mano, un papel blanco o una tarjeta gris detrás ayuda mucho.",
        "Escala: ponga una moneda, regla o el dedo al lado en al menos una foto.",
        "Varias fotos del MISMO individuo (un set): cada una desde otro ángulo.",
        "Además una foto de contexto: la planta completa o el lugar donde estaba.",
    ],
    "plagas": [
        "Set: dorsal (de arriba), lateral (de lado: patas, trompa, antenas), ventral (de abajo) y "
        "el daño que produce.",
        "Insectos rápidos: póngalos unos minutos en el refrigerador (en un frasco) y fotografíelos "
        "sobre papel blanco.",
        "Larvas: muestre la cabeza y si tiene patas (gusano blanco con patas = pololo; sin patas = "
        "gorgojo).",
        "Ácaros y eriófidos: use el zoom máximo o una lupa delante de la cámara.",
        "Si hay huevos, larvas y adultos, sáquelos por separado y elija el estadio en cada captura.",
    ],
    "malezas": [
        "Set: planta completa, hoja por arriba (haz), hoja por abajo (envés) y flor o semilla.",
        "Si puede, saque una con la raíz o la base (rizomas, bulbitos, estolones) sobre el suelo.",
        "Gramíneas: acerque la unión de la hoja con el tallo (lígula y aurículas) y la espiga.",
        "La flor es lo que más ayuda: si no tiene, vuelva a fotografiarla cuando florezca.",
        "PlantNet funciona mejor con una foto por órgano (hoja, flor, fruto, planta).",
    ],
    "enfermedades": [
        "Set: órgano completo (hoja, caña o fruta entera) y detalle de la lesión de cerca.",
        "Incluya el borde de la lesión con tejido sano al lado.",
        "Si hay moho, polvillo o puntitos negros, saque uno muy de cerca (zoom o lupa).",
        "Raíces y cuello: lave la tierra y corte la corteza para mostrar el color interno.",
        "Saque también la planta completa y si el daño está en manchones o en una sola planta.",
    ],
}


# Guía ilustrada (láminas en assets/ui/guia, ver tools/make_photo_guide.py):
# (lámina, título, texto corto). Primero las de la sección, después las generales.
PHOTO_CARDS = {
    "plagas": [
        ("p_set", "Un set por individuo", "Cuatro fotos del mismo bicho: de arriba, de lado, de abajo y el "
                                         "daño que hace. «Set guiado» abre la cámara para cada una."),
        ("p_frio", "Insectos que se arrancan", "Unos minutos en un frasco en el refrigerador los deja "
                                               "quietos; después, sobre papel blanco."),
        ("p_larva", "Larvas: muestre cabeza y patas", "Gusano blanco con 3 pares de patas = pololo; sin "
                                                      "patas = gorgojo (burrito, cabrito)."),
        ("p_dano", "El daño también cuenta", "Mordeduras en media luna, hojas enrolladas, fruta picada: "
                                             "con el insecto al lado es mejor."),
    ],
    "malezas": [
        ("m_set", "Un set por planta", "Planta completa, hoja por arriba, hoja por abajo y flor o semilla. "
                                       "La flor es lo que más ayuda."),
        ("m_raiz", "Si puede, con la raíz", "Rizomas, bulbitos y estolones distinguen especies "
                                            "parecidas."),
        ("m_graminea", "Gramíneas (pastos)", "Acerque la unión de la hoja con el tallo (lígula y aurículas) "
                                             "y la espiga."),
    ],
    "enfermedades": [
        ("e_set", "Completo y de cerca", "Primero la hoja, caña o fruta entera; después el detalle de la "
                                         "lesión."),
        ("e_borde", "Con el borde sano", "La IA reconoce mejor el avance de la lesión con tejido sano al "
                                         "lado."),
        ("e_moho_raiz", "Moho, puntitos y cuello", "Moho o puntitos negros: zoom máximo o lupa. En raíz y "
                                                   "cuello: lave la tierra y corte la corteza."),
    ],
    "_": [
        ("g_enfoque", "Nítida", "Toque la pantalla sobre el objeto antes de disparar y no se mueva."),
        ("g_llenar", "Que llene la foto", "Acérquese o use zoom 2×: el objeto debe ocupar buena parte."),
        ("g_luz", "Luz pareja", "Sombra suave o día nublado. Evite el sol directo y el flash."),
        ("g_fondo", "Fondo simple", "Una hoja, la mano o un papel detrás ayudan mucho a la IA."),
        ("g_escala", "Escala", "Una moneda, regla o el dedo al lado en al menos una foto."),
        ("g_contexto", "Y una de contexto", "La planta completa o el lugar donde estaba."),
    ],
}


def photo_cards(section: str) -> list[tuple[str, str, str]]:
    return PHOTO_CARDS.get(section, []) + PHOTO_CARDS["_"]


# ----------------------------------------------------------------- búsqueda
def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(ch for ch in t if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def species_for(section: str, crop: str | None = None) -> list[dict]:
    """Fichas de la sección (las del cultivo `crop`, si se da: frambuesa, arandano, cranberry)."""
    out = [s for s in SPECIES if s["section"] == section]
    if crop:
        out = [s for s in out if any(CROPS[ch] == crop for ch in s["crops"])]
    return out


def find(section: str, name: str = "", scientific: str = "") -> dict | None:
    """Ficha por nombre científico (o común). Si no hay una exacta, la del mismo género."""
    sci, nm = _norm(scientific), _norm(name)
    pool = [s for s in SPECIES if s["section"] == section]
    for s in pool:
        if sci and _norm(s["scientific"]) == sci:
            return s
    for s in pool:
        if nm and _norm(s["name"]) == nm:
            return s
    # Sin ficha exacta: la del género, solo si la ficha es del género entero («Juncus spp.»),
    # así «Rumex acetosa» no cae en «Rumex acetosella».
    genus = sci.split(" ")[0] if sci else ""
    if genus and genus not in ("abiotico", "virus"):
        for s in pool:
            words = _norm(s["scientific"]).split(" ")
            if words[0] == genus and (len(words) == 1 or words[1] in ("spp", "sp")):
                return s
    return None


def crops_text(entry: dict) -> str:
    return ", ".join(CROP_NAMES[CROPS[ch]] for ch in entry["crops"])


def ficha_text(entry: dict) -> str:
    """Texto de la ficha (con marcas de Kivy: [b]…[/b])."""
    parts = [("Cómo reconocerla", entry["look"]), ("Estadios", entry["stages"]),
             ("Daño / síntoma", entry["damage"]), ("Se confunde con", entry["confuse"]),
             ("Cultivos", crops_text(entry))]
    return "\n\n".join(f"[b]{k}:[/b] {v}" for k, v in parts if v)


def photo_tips(section: str) -> list[str]:
    return PHOTO_GUIDE.get(section, []) + PHOTO_GUIDE["_"]


def seed(db) -> int:
    """Agrega al catálogo de AeonScout las especies de la guía que falten (una vez por versión
    de la guía). No toca las que el usuario ya tiene ni las que desactivó."""
    key = "scout_guide_v1"
    if db.get_setting(key):
        return 0
    n = 0
    for s in SPECIES:
        have = db.query_one("SELECT id FROM scout_species WHERE section=? AND (name=? OR "
                            "(scientific<>'' AND scientific=?))", (s["section"], s["name"], s["scientific"]))
        if have:
            continue
        db.execute("INSERT OR IGNORE INTO scout_species(section, name, scientific, kind, created_at) "
                   "VALUES (?,?,?,?,datetime('now'))",
                   (s["section"], s["name"], "" if s["scientific"] == "Abiótico" else s["scientific"],
                    s["kind"]))
        n += 1
    db.set_setting(key, True)
    return n
