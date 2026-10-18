# Проверка общего блока сайта —19.10.2026

База cd69fe1, согласованный scope из decisions.md. Этот checkpoint описывает
проверку, не подтверждает production до завершения CI/deploy.

-101 backend tests shared editor/context/home/publiccontent passed.
-7 Node tests actualscriptcontext/inline/homepage passed.
-37 повторных homepage/bridge tests passed после reserved sitecode.
-1vaultdiscoverytest passed.
-126 tests полного затронутого набора, включая все опубликованные статьи, passed222,57с.
-Внешний вид home/full/subscribe/popup360/430/768/899/900/901/1440.
  Evidence внеGit D:/Codex/evidence/channel-rollout-home-20261019-b,
  channel-rollout-states-20261019-a, channel-rollout-inline-20261019-c.
  Предыдущие inline-a/b перекрывал popup, они не доказательство обычного состояния.
-Reviewcode/security/test/docs: максимум2волны, доказанные findingисправлены.
-Layoutwave2 clean по неперекрытым screenshot; code/security/test/docs также clean.

Известное ограничение MAX: общая карточка ведёт в действующий канал; отдельный
pinURL ещё неподтверждён. Счётчик исключён. Constructor/events/botgreeting —
следующий отдельный срез, в этот website diff не входят.
