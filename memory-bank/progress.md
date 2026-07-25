# Progress & Roadmap: Jelotia Imposer

## Completed Milestones
- Repository scaffolding.
- Virtual environment and dependencies mapped.
- Domain vs. Database separation defined.
- Phase 0 to Phase 4 (Architecture, Core Engines, GUI, Automation).
- Phase 5: Export Engine & Intégration RIP (PDF/X, TIFF, JPEG support, XML Job Tickets).
- Documentation: Redédaction complète d'un README.md entreprise hyper-détaillé selon le standard MastodonAffiliate (Badges, Table des matières, Architectures, Engin Preflight/Nesting/Export/Repères, Stack, Quick Start uv, et FAQ).


## Current Task: Phase 6 Continuation (Tests, QA & Performance)
#### Tests unitaires
- [ ] Coverage ≥ 80% sur tous les moteurs
- [ ] Tests preflight : 100% des règles couvertes
- [ ] Tests nesting : fill_rate moyen ≥ 75% sur corpus test
- [ ] Tests export : conformité PDF/X (pdfinfo + veraPDF)
- [ ] Tests correction : avant/après sur 20 types d'anomalies

#### Tests d'intégration
- [ ] Scénario end-to-end : dossier 500 fichiers mixtes
- [ ] Test Hot Folder : 8h de surveillance continue
- [ ] Test crash recovery : kill process → reprise
- [ ] Test concurrent : 8 workers simultanés
- [ ] Test mémoire : aucune fuite sur 2h de traitement continu

#### Tests de performance
- [ ] Benchmark : 1 000 fichiers, mesure temps total
- [ ] Profiling (cProfile / py-spy) → optimiser goulots
- [ ] Test charge : 10 000 fichiers en 24h simulées
- [ ] Optimisation si throughput insuffisant

## Future Roadmap
- Phase 6: Tests, QA & Performance
- Phase 7: Packaging & Documentation
