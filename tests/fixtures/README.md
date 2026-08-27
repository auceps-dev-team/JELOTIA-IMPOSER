# Fixtures de test

## `ISOcoated_v2_bas.ICC` — profil CMJN FOGRA39

Profil de sortie CMJN utilisé par les tests de gestion des couleurs et
d'export PDF/X.

| | |
|---|---|
| **Nom** | ISO Coated v2 (basICColor) |
| **Condition** | FOGRA39 — offset feuille sur papier couché, TAC 330 % |
| **Éditeur** | basICColor GmbH |
| **Licence** | **zlib** (voir `LICENSE-ZLIB-bICC`) — approuvée OSI, autorise explicitement l'usage commercial et la redistribution |
| **Source** | paquet Debian `icc-profiles-free` (composant `main`, donc DFSG-libre), sous-paquet `icc-profiles-basiccolor-printing2009` |
| **Taille** | 1,0 Mo |

### Pourquoi celui-ci et pas celui de l'ECI

Le profil FOGRA39 le plus connu est `ISOcoated_v2_eci.icc`, distribué
gratuitement par l'ECI. Il porte cependant la mention embarquée
« *(c) Copyright 2000-2006 Heidelberger Druckmaschinen AG. **All Rights
Reserved*** » — gratuit n'est pas libre. Debian le classe d'ailleurs en
**non-free** (paquet `icc-profiles`), alors que le profil basICColor retenu ici
est dans **main**.

Comme Jelotia Imposer est destiné à être commercialisé, seul un profil dont la
licence autorise sans ambiguïté la redistribution commerciale peut être versé
au dépôt. La licence zlib le permet explicitement.

### Pourquoi un fichier versionné plutôt qu'une découverte système

Les tests cherchaient auparavant `C:/Windows/System32/.../RSWOP.icm` et se
**sautaient silencieusement** en son absence — c'est-à-dire sur tout runner de
CI. La chaîne colorimétrique et l'export PDF/X, soit exactement ce que
l'imprimeur reçoit, n'étaient donc validés nulle part. Un vert obtenu en sautant
les tests n'est pas un vert.

Aucune dépendance du projet ne fournit de profil CMJN (contrairement aux
polices : `Bitstream Vera` est livrée avec reportlab et sert aux tests de
polices embarquées). Le fichier doit donc être versionné.

### Note d'encrage

Ce profil est conçu pour l'**offset couché** : un noir RGB pur converti avec
l'intention perceptuelle en ressort à **330 % d'encre**, ce qui est conforme à
sa spécification. Pour l'impression numérique et le grand format — le métier de
JELOTIA — cette charge est excessive. Les tests ne présupposent donc aucun
niveau d'encrage précis : ils vérifient que la conversion est bien
colorimétrique et que le profil est embarqué, pas qu'elle produit tel dosage,
qui dépend légitimement du profil choisi.
