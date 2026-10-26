# W&F source-format fixtures

`wf_legacy_xls.json` contains zlib-compressed, base64-encoded **synthetic BIFF8
XLS workbooks**. Tests decode them into temporary files; the fixture generation
writer (`xlwt` 1.3.0) is not needed to run tests and is not an application
dependency. `xlrd`, the application XLS reader, is installed by requirements.txt.

The six workbooks contain Collections/Returned row-4 and row-6 layouts with
synthetic totals, the two legacy synthetic Insights schemas, the 0.23.4 combined Banner schema, and a 1904-date-
epoch example. They use `TEST-1`, `0000123`, `Synthetic Student`, `CONSUMER-1`
and year-2099 dates. The hold example also includes 9999-12-31. They contain
no production records, macros, credentials or external connections.
