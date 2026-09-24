# Qualitative failure analysis (P9-04)

Mechanically selected **n = 20** cases from `results/failure_cases.json`. Shortlist misses in this set: **0** (candidate-generation vs reranker).

Review uses only sealed patch/test/ranking artifacts. No new model calls. Categories are explanatory; they do not change metrics, prompts, or shortlist size. All 20 mechanically selected IDs are covered exactly once.

## Category counts

- Jev overvalued superficial similarity: 6
- behavioral semantic match: 5
- cross-class relationship: 3
- identifier/name match: 2
- Jev missed indirect dependency: 1
- ambiguous test responsibility: 1
- large/truncated patch: 1
- test source provided useful clue: 1

## Cases

| ID | Arm | BM25 r | Jev r | Δ | Trig∈200 | Category | Evidence |
| --- | --- | ---: | ---: | ---: | --- | --- | --- |
| `JacksonDatabind-62` | gains | 131 | 1 | 130 | yes | behavioral semantic match | Patch removes CollectionDeserializer array-delegate creator path (canCreateUsingArrayDelegate). Jev ranks ArrayDelegatorCreatorForCollectionTest #1 (p=0.70); BM25 ranks it #131. Reranker win: semantic link between array-delegate creation and the named creator test, not a shortlist miss. |
| `JacksonDatabind-35` | gains | 114 | 3 | 111 | yes | behavioral semantic match | Patch edits AsWrapperTypeDeserializer; trigger WrapperObjectWithObjectIdTest. Jev places it #3 among typed/wrapper deserialization tests; BM25 #114 behind generic deserializer/factory names. Behavioral wrapper/type-id match. |
| `JacksonDatabind-38` | gains | 93 | 5 | 88 | yes | cross-class relationship | Patch changes CollectionType/MapType/SimpleType construction; trigger is interop.DeprecatedTypeHandling1102Test (explicit collection/map type APIs). Jev #5 after other type/generics tests; BM25 #93 stuck on TestTypeFactory lexical neighbors. Failure mode avoided: cross-package type-API consumer test. |
| `JacksonDatabind-49` | gains | 85 | 8 | 77 | yes | behavioral semantic match | WritableObjectId change; trigger objectid.AlwaysAsReferenceFirstTest. Jev packs ObjectId tests in the top ranks (trigger #8); BM25 #85 with serializer config noise. Object-id / always-as-reference behavior match. |
| `JacksonDatabind-47` | gains | 63 | 1 | 62 | yes | behavioral semantic match | AnnotationIntrospector serialize-typing change; triggers TestJsonSerialize / TestJsonSerializeAs (broken annotation / specialized-as). Jev #1/#4; BM25 #63. Reranker maps introspector annotation logic to @JsonSerialize tests. |
| `JacksonDatabind-72` | gains | 50 | 1 | 49 | yes | identifier/name match | InnerClassProperty ↔ creators.InnerClassCreatorTest. Shared InnerClass token; Jev #1 vs BM25 #50. Dominant signal is the identifier overlap Jev promoted that BM25 under-weighted in the full suite ordering. |
| `JacksonDatabind-15` | gains | 48 | 1 | 47 | yes | behavioral semantic match | Patch touches StdDelegatingSerializer / converter serializer path; trigger convert.TestConvertingSerializer at Jev #1 vs BM25 #48 (BM25 preferred TestBeanConversions). Converting/delegating serializer semantics. |
| `Cli-21` | gains | 49 | 4 | 45 | yes | test source provided useful clue | Removes WriteableCommandLine get/setCurrentOption; trigger BugCLI150Test. Jev elevates bug.* regression tests (trigger #4) while BM25 #49 prefers option/Group unit tests. Bug-test source aligns with the current-option API loss. |
| `Math-13` | gains | 50 | 7 | 43 | yes | cross-class relationship | AbstractLeastSquaresOptimizer.squareRoot(DiagonalMatrix) change; trigger optimization.fitting.PolynomialFitterTest (uses the optimizer). Jev #7 in an optimizer/fitter cluster; BM25 #50 distracted by EigenDecomposition matrix tests. Fitter→optimizer dependency, not same-class naming. |
| `Math-14` | gains | 44 | 5 | 39 | yes | cross-class relationship | Weight / AbstractLeastSquaresOptimizer diagonal-weight change; trigger fitting.PolynomialFitterTest. Jev #5; BM25 #44 again ranks linear-algebra tests first. Same cross-class fitter→optimizer pattern as Math-13. |
| `JacksonDatabind-103` | losses | 7 | 26 | -19 | yes | large/truncated patch | Multi-file exception/context patch (~14.8k chars, patch_truncated=true). Trigger exc.BasicExceptionTest. BM25 #7 (exception lexical cues); Jev #26 among unrelated deser/creator tests. Truncated wide patch harms reranker focus. |
| `Math-104` | losses | 2 | 19 | -17 | yes | Jev overvalued superficial similarity | Gamma.java ↔ special.GammaTest. BM25 #2 via Gamma name tokens; Jev #19 after ChiSquare/Poisson/inference tests. Reranker preferred neighboring stats distributions over the matching GammaTest. |
| `JacksonDatabind-51` | losses | 17 | 25 | -8 | yes | Jev overvalued superficial similarity | TypeDeserializerBase change; trigger jsontype.TestCustomTypeIdResolver. BM25 #17; Jev #25 after polymorphic/generics deser tests. Superficial type-system theme outranked the custom type-id resolver test. |
| `Lang-6` | losses | 5 | 13 | -8 | yes | Jev missed indirect dependency | CharSequenceTranslator code-point indexing change; trigger StringUtilsTest::testEscapeSurrogatePairs (StringUtils escape uses the translator). BM25 #5 includes StringUtilsTest; Jev #13 after direct translate.* tests. Missed the StringUtils→translator dependency. |
| `Lang-61` | losses | 1 | 5 | -4 | yes | Jev overvalued superficial similarity | StrBuilder ↔ StrBuilderTest (clear name match). BM25 #1; Jev #5 behind StringUtilsEqualsIndexOfTest and other text utils. Overvalued adjacent string utilities versus the matching *Test class. |
| `Cli-28` | losses | 2 | 4 | -2 | yes | Jev overvalued superficial similarity | Parser change; trigger ValueTest. BM25 #2; Jev #4 after BugCLI13/BugCLI148. Bug-regression tests outranked the value-parsing test that BM25 surfaced. |
| `Lang-26` | losses | 1 | 3 | -2 | yes | Jev overvalued superficial similarity | FastDateFormat ↔ FastDateFormatTest. BM25 #1; Jev #3 behind ExtendedMessageFormatTest / DateFormatUtilsTest. Neighboring date-format tests displaced the identifier-matched trigger. |
| `Cli-32` | losses | 1 | 2 | -1 | yes | identifier/name match | HelpFormatter ↔ HelpFormatterTest. BM25 #1 via name; Jev #2 after BugCLI162Test. Small loss: BM25's identifier match beat Jev's bug-test preference by one rank. |
| `JacksonDatabind-100` | losses | 1 | 2 | -1 | yes | ambiguous test responsibility | TreeTraversingParser patched; trigger node.TestConversions (not TestTreeTraversingParser). Jev #1 ranks TestTreeTraversingParser (class-name match to the modified file); BM25 #1 ranks TestConversions (actual trigger). Same-package name match is the wrong positive; responsibility is ambiguous. |
| `Lang-47` | losses | 1 | 2 | -1 | yes | Jev overvalued superficial similarity | StrBuilder ↔ StrBuilderTest. BM25 #1; Jev #2 after StrBuilderAppendInsertTest. Near-miss: related StrBuilder* test preferred over the labeled trigger class. |

## Provenance

- JSON: `results/failure_analysis.json`
- failure_cases sha256=`9a2e8fb280bbb1c2e75bece97fa74ef8a0e3c79c5a2a991f956cb1b4934eb00b`
