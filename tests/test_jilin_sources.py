import hashlib
import tempfile
import unittest
from pathlib import Path
from scrapling.engines.toolbelt.custom import Response
from legal_store import LegalStore
from jilin_sources import PublicReader, extract_rule, detail_attachment, ingest_sample, region_code
import jilin_sources


def page(url, body, status=200):
    return Response(url=url, content=body.encode(), status=status, reason='test', cookies={}, headers={}, request_headers={})


class JilinTests(unittest.TestCase):
    def test_failure_is_not_completed_and_http_evidence_is_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            reader=PublicReader(fetch=lambda url: page(url,'拒绝',403),delay=0)
            report=jilin_sources.run_samples(root,[self.sample],reader)
            self.assertFalse(report['complete'])
            self.assertTrue(report['attempt_finished'])
            self.assertEqual(report['failed'],1)
            evidence=list((root/'data/jilin-samples/responses').glob('*/response.bin'))
            self.assertTrue(evidence)
            self.assertEqual(evidence[0].read_bytes(),'拒绝'.encode())

    def test_government_issuer_and_kind_cannot_be_forged(self):
        for patch in ({'issuer':'松原市人民政府','region_name':'松原市'},
                      {'kind':'administrative_norm'}):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp); store=LegalStore(root/'data/legal.sqlite3')
                reader=PublicReader(fetch=lambda url: page(url,'',404) if url.endswith('robots.txt') else page(url,self.body),delay=0)
                row=ingest_sample(root,{**self.sample,**patch},reader,store)
                self.assertEqual(row['status'],'failed')
                self.assertEqual(store.health()['versions'],0)
                store.close()

    def test_actual_rule_template_uses_visible_title_and_issuer(self):
        body='<div id="zoom"><!--<div class="DOCTITLE">忽略</div>--><div class="Custom_UnionStyle"><p>'+self.title+'</p><p>吉林省人民政府令第285号公布</p><p>第一条　测试原文。</p></div></div><div class="rul_note">吉林省人民政府发布</div>'
        self.assertTrue(extract_rule(body.encode(),self.title).startswith(self.title))
        with self.assertRaises(ValueError):extract_rule(body.replace('吉林省人民政府发布','松原市人民政府发布').encode(),self.title)

    def test_partial_original_is_preserved_and_recovers_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'original.doc'
            path.write_bytes(b'ori')
            jilin_sources.keep_original(path,b'original')
            self.assertEqual(path.read_bytes(),b'original')
            self.assertEqual(next(path.parent.glob('*.incomplete-*')).read_bytes(),b'ori')
            with self.assertRaises(ValueError):jilin_sources.keep_original(path,b'different')

    def test_batch_cap_and_ids_fail_before_any_database_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for samples in ([self.sample]*21,[{**self.sample,'id':'../outside'}]):
                with self.assertRaises(ValueError):jilin_sources.run_samples(root,samples,None)
            self.assertFalse((root/'data/legal.sqlite3').exists())

    def test_batch_reports_acquisition_and_ingestion_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def fetch(url):
                return page(url,'',404) if url.endswith('/robots.txt') else page(url,self.body)
            report=jilin_sources.run_samples(root,[self.sample],PublicReader(fetch=fetch,delay=0))
            self.assertEqual(report['originals_acquired'],1)
            self.assertEqual(report['ingested'],1)
            self.assertEqual(report['human_approved_this_run'],0)
            self.assertTrue(report['complete'])

    def test_source_write_failure_rolls_back_new_body_index_and_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=LegalStore(root/'data/legal.sqlite3')
            try:
                store.db.executescript("CREATE TRIGGER fail_source BEFORE INSERT ON provenance BEGIN SELECT RAISE(ABORT,'injected source failure'); END;")
                reader=PublicReader(fetch=lambda url: page(url,'',404) if url.endswith('robots.txt') else page(url,self.body),delay=0)
                row=ingest_sample(root,self.sample,reader,store)
                self.assertEqual(row['status'],'failed')
                self.assertEqual(row['phase'],'store_roundtrip')
                for table in ('versions','search_index','provenance','audit'):
                    self.assertEqual(store.db.execute('SELECT count(*) FROM '+table).fetchone()[0],0,table)
                self.assertTrue((root/row['original_path']).exists(),'数据库回滚不删除原件留证')
            finally:store.close()

    def setUp(self):
        self.url = 'https://xxgk.jl.gov.cn/szf/gzk/202509/t20250924_9326899.html'
        self.title = '吉林省行政调解规定'
        self.body = '<html><div id="zoom"><div class="DOCTITLE">'+self.title+'</div><div class="DocAbstract">吉林省人民政府令</div><div class="Custom_UnionStyle"><p>第一条　规定内容。</p><p>第二条　施行。</p></div></div><div class="rul_note">吉林省人民政府发布</div><footer>导航不得进入正文</footer></html>'
        self.sample = {'id':'9326899','title':self.title,'url':self.url,'kind':'government_rule',
                       'region_name':'吉林省','issuer':'吉林省人民政府'}

    def test_region_distinguishes_city_and_unknown(self):
        self.assertEqual(region_code('松原市','松原市人民代表大会常务委员会'),'CN-JL-SY')
        self.assertEqual(region_code('长春市','长春市人民政府'),'CN-JL-CC')
        with self.assertRaises(ValueError):region_code('未知县','未知县人民政府')
        with self.assertRaises(ValueError):region_code('吉林省','松原市人民政府')

    def test_rule_extract_excludes_navigation_and_checks_identity(self):
        text = extract_rule(self.body.encode(),self.title)
        self.assertIn('第二条',text)
        self.assertNotIn('导航',text)
        for payload in (b'<html>captcha</html>', self.body.replace(self.title,'不匹配').encode()):
            with self.assertRaises(ValueError):extract_rule(payload,self.title)

    def test_attachment_is_same_origin_and_exact_title(self):
        url='https://www.jlrd.gov.cn/jlsjk/202608/t20260811_9679876.html'
        body='<div class="bt">测试条例</div><span id="zdztText">吉林省人民代表大会常务委员会</span><a href="./sample.docx">附件</a>'
        self.assertEqual(detail_attachment(body.encode(),url,'测试条例','吉林省人民代表大会常务委员会'),
                         'https://www.jlrd.gov.cn/jlsjk/202608/sample.docx')
        with self.assertRaises(ValueError):detail_attachment(body.replace('./sample.docx','https://example.com/x.docx').encode(),url,'测试条例','吉林省人民代表大会常务委员会')

    def test_unique_pdf_attachment_is_supported_and_mixed_attachments_not_ignored(self):
        url='https://www.jlrd.gov.cn/jlsjk/202608/t20260811_9679877.html'
        body='<div class="bt">测试条例</div><span id="zdztText">吉林省人大常委会</span><a href="./original.pdf">正文</a>'
        try:
            attachment=detail_attachment(body.encode(),url,'测试条例','吉林省人大常委会')
        except ValueError as exc:
            self.fail(f'唯一PDF附件应可识别：{exc}')
        self.assertEqual(attachment,'https://www.jlrd.gov.cn/jlsjk/202608/original.pdf')
        for href in ('./attachment.docx','./attachment.PDF','./attachment.pdf?download=1','./attachment.xlsx'):
            mixed=body+f'<a href="{href}">另一附件</a>'
            with self.subTest(href=href), self.assertRaises(ValueError):
                detail_attachment(mixed.encode(),url,'测试条例','吉林省人大常委会')

    def test_same_title_alternate_formats_are_recorded_not_extra_annexes(self):
        url='https://www.jlrd.gov.cn/jlsjk/202608/example.html'
        head='<div class="bt">测试条例</div><span id="zdztText">吉林省人大常委会</span>'
        body=head+'<a href="a.wps">测试条例.wps</a><a href="a.pdf">测试条例.pdf</a>'
        try: selected=detail_attachment(body.encode(),url,'测试条例','吉林省人大常委会')
        except ValueError as exc:self.fail(f'同名格式副本应明确记录并选择：{exc}')
        self.assertTrue(selected.endswith('a.pdf'))
        for addition in ('<a href="b.pdf">测试条例.pdf</a>', '<a href="extra.doc">附件一.doc</a>'):
            with self.assertRaises(ValueError):
                detail_attachment((body+addition).encode(),url,'测试条例','吉林省人大常委会')

    def test_pdf_ingest_keeps_manifest_and_source_fields(self):
        from test_official_pdf import pdf
        payload=pdf()
        sample={'id':'123','title':'Test Law','url':'https://www.jlrd.gov.cn/jlsjk/202608/example.html',
                'issuer':'吉林省人大常委会','region_name':'吉林省','kind':'local_regulation'}
        detail='<div class="bt">Test Law</div><span id="zdztText">吉林省人大常委会</span><a href="original.pdf">正文</a>'
        def fetch(url):
            if url.endswith('/robots.txt'):return page(url,'',404)
            if url.endswith('.pdf'):
                return Response(url=url,content=payload,status=200,reason='test',cookies={},headers={},request_headers={})
            return page(url,detail)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=LegalStore(root/'data/legal.sqlite3')
            try:
                row=ingest_sample(root,sample,PublicReader(fetch=fetch,delay=0),store)
                self.assertEqual(row['status'],'ingested_quarantine')
                stored=store.detail(row['version_id'])
                self.assertEqual(stored['provenance']['pages'][0]['page'],1)
                self.assertTrue((root/row['original_path']).with_name('pdf-extraction.json').exists())
                self.assertTrue(stored['provenance']['original_url'].endswith('.pdf'))
                self.assertEqual(stored['provenance']['uncompared_alternative_urls'],[])
                self.assertEqual(store.health()['published'],0)
            finally:store.close()

    def test_matching_download_names_do_not_have_to_equal_legal_title(self):
        url='https://www.jlrd.gov.cn/jlsjk/202608/example.html'
        head='<div class="bt">测试条例规定</div><span id="zdztText">吉林省人大常委会</span>'
        for stem in ('2.测试条例规定', '《测试条例规定》', '2.测试条例'):
            body=head+f'<a href="a.docx">{stem}.docx</a><a href="a.pdf">{stem}.pdf</a>'
            with self.subTest(stem=stem):
                try:
                    selected, alternatives=jilin_sources.detail_attachments(body.encode(),url,'测试条例规定','吉林省人大常委会')
                except ValueError as exc:
                    self.fail(f'下载名应分组而非冒充法律标题：{exc}')
                self.assertTrue(selected.endswith('a.docx'))
                self.assertEqual(alternatives,[url.rsplit('/',1)[0]+'/a.pdf'])
        mixed=head+'<a href="a.docx">测试条例规定.docx</a><a href="a.pdf">附件一.pdf</a>'
        with self.assertRaises(ValueError):
            jilin_sources.detail_attachments(mixed.encode(),url,'测试条例规定','吉林省人大常委会')

    def test_configured_pdf_choice_is_explicit_and_keeps_other_original_url(self):
        from test_official_pdf import pdf
        payload=pdf()
        sample={'id':'124','title':'Test Law','url':'https://www.jlrd.gov.cn/jlsjk/202608/example.html',
                'issuer':'吉林省人大常委会','region_name':'吉林省','kind':'local_regulation',
                'preferred_format':'pdf'}
        detail='<div class="bt">Test Law</div><span id="zdztText">吉林省人大常委会</span><a href="a.doc">Test Law.doc</a><a href="a.pdf">Test Law.pdf</a>'
        calls=[]
        def fetch(url):
            calls.append(url)
            if url.endswith('/robots.txt'):return page(url,'',404)
            if url.endswith('.pdf'):
                return Response(url=url,content=payload,status=200,reason='test',cookies={},headers={},request_headers={})
            if url.endswith('.doc'):return page(url,'unsupported word')
            return page(url,detail)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=LegalStore(root/'data/legal.sqlite3')
            try:
                row=ingest_sample(root,sample,PublicReader(fetch=fetch,delay=0),store)
                self.assertEqual(row['status'],'ingested_quarantine')
                self.assertFalse(any(url.endswith('.doc') for url in calls))
                provenance=store.detail(row['version_id'])['provenance']
                self.assertEqual(provenance['source_format'],'pdf')
                self.assertEqual(provenance['uncompared_alternative_urls'],[sample['url'].rsplit('/',1)[0]+'/a.doc'])
                from legal_citations import citation_for
                stored=store.detail(row['version_id'])
                card=citation_for(stored,0,len(stored['text']))
                self.assertEqual(card['uncompared_alternative_urls'],provenance['uncompared_alternative_urls'])
                self.assertEqual(store.health()['published'],0)
            finally:store.close()

    def test_shared_truncated_filename_never_replaces_body_title_check(self):
        from test_official_pdf import pdf
        from test_official_docx import document
        sample={'id':'125','title':'Test Law','url':'https://www.jlrd.gov.cn/jlsjk/202608/example.html',
                'issuer':'吉林省人大常委会','region_name':'吉林省','kind':'local_regulation'}
        detail='<div class="bt">Test Law</div><span id="zdztText">吉林省人大常委会</span><a href="a.docx">2.Test.docx</a><a href="a.pdf">2.Test.pdf</a>'
        payloads={'docx':document('<w:p><w:r><w:t>Wrong Law</w:t></w:r></w:p>'),
                  'pdf':pdf([['Wrong Law','Article 1. Content.']])}
        for preferred_format in payloads:
            calls=[]
            def fetch(url):
                calls.append(url)
                if url.endswith('/robots.txt'):return page(url,'',404)
                if url.endswith(('.pdf','.docx')):
                    return Response(url=url,content=payloads[url.rsplit('.',1)[1]],status=200,
                                    reason='test',cookies={},headers={},request_headers={})
                return page(url,detail)
            with self.subTest(format=preferred_format), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);store=LegalStore(root/'data/legal.sqlite3')
                try:
                    row=ingest_sample(root,{**sample,'preferred_format':preferred_format},PublicReader(fetch=fetch,delay=0),store)
                    self.assertEqual(row['phase'],'extract')
                    self.assertEqual(row['status'],'failed')
                    self.assertEqual(store.health()['versions'],0)
                    self.assertEqual(len([x for x in calls if x.endswith(('.pdf','.docx'))]),1)
                finally:store.close()

    def test_bad_format_preference_does_not_fall_back_or_skip_attachment_conflict(self):
        url='https://www.jlrd.gov.cn/jlsjk/202608/example.html'
        head='<div class="bt">测试条例</div><span id="zdztText">吉林省人大常委会</span>'
        body=head+'<a href="a.pdf">测试条例.pdf</a>'
        for preference in ('docx','wps','exe',''):
            with self.subTest(preference=preference):
                try:
                    jilin_sources.detail_attachments(body.encode(),url,'测试条例','吉林省人大常委会',preferred_format=preference)
                except TypeError as exc:self.fail(f'尚未实现明确格式选择：{exc}')
                except ValueError:pass
                else:self.fail('配置错误不得静默降级')
        for addition in ('<a href="b.pdf">测试条例.pdf</a>', '<a href="b.docx">附件一.docx</a>'):
            try:
                with self.assertRaises(ValueError):
                    jilin_sources.detail_attachments((body+addition).encode(),url,'测试条例','吉林省人大常委会',preferred_format='pdf')
            except TypeError as exc:self.fail(f'尚未实现明确格式选择：{exc}')

    def test_robots_and_off_domain_prevent_document_fetch(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            return page(url,'User-agent: *\nDisallow: /')
        reader=PublicReader(fetch=fetch,delay=0)
        with self.assertRaises(ValueError):reader.get(self.url)
        with self.assertRaises(ValueError):reader.get('https://example.com/law')
        self.assertEqual(calls,['https://xxgk.jl.gov.cn/robots.txt'])

    def test_duplicate_pdfs_require_every_original_to_match_selected_body(self):
        from test_official_pdf import pdf
        from test_official_docx import document
        sample={'id':'126','title':'Test Law','url':'https://www.jlrd.gov.cn/jlsjk/202608/example.html',
                'issuer':'吉林省人大常委会','region_name':'吉林省','kind':'local_regulation'}
        detail='<div class="bt">Test Law</div><span id="zdztText">吉林省人大常委会</span><a href="a.docx">Test Law.docx</a><a href="a.pdf">Test Law.pdf</a><a href="b.pdf">Test Law.pdf</a>'
        docx=document('<w:p><w:r><w:t>Test Law</w:t></w:r></w:p><w:p><w:r><w:t>Article 1. Content.</w:t></w:r></w:p>')
        first=pdf();equal=pdf([['Test Law','Article 1. Content.']]);different=pdf([['Test Law','Article 1. Changed.']])
        for kind,second in (('equal',equal),('different',different),('broken',b'not pdf')):
            calls=[]
            def fetch(url):
                calls.append(url)
                if url.endswith('/robots.txt'):return page(url,'',404)
                for suffix,payload in (('a.docx',docx),('a.pdf',first),('b.pdf',second)):
                    if url.endswith(suffix):return Response(url=url,content=payload,status=200,reason='test',cookies={},headers={},request_headers={})
                return page(url,detail)
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);store=LegalStore(root/'data/legal.sqlite3')
                try:
                    row=ingest_sample(root,sample,PublicReader(fetch=fetch,delay=0),store)
                    if kind=='equal':
                        self.assertEqual(row['status'],'ingested_quarantine')
                        self.assertEqual(len(row['compared_pdf_originals']),2)
                        self.assertEqual(row['uncompared_alternative_urls'],[])
                        from legal_citations import citation_for
                        saved=store.detail(row['version_id']);card=citation_for(saved,0,len(saved['text']))
                        self.assertEqual(card['compared_pdf_originals'],row['compared_pdf_originals'])
                        self.assertEqual(card['pages'],[],'不能把PDF页码套到Word字符偏移')
                        again=ingest_sample(root,sample,PublicReader(fetch=fetch,delay=0),store)
                        self.assertEqual(again['version_id'],row['version_id'])
                        self.assertEqual(store.health()['versions'],1)
                    else:
                        self.assertEqual(row['status'],'failed')
                        self.assertEqual(row['phase'],'compare_pdf_copies')
                        self.assertEqual(store.health()['versions'],0)
                    for payload in (first,second):
                        path=root/'data/jilin-samples/126'/hashlib.sha256(payload).hexdigest()/'original.pdf'
                        self.assertEqual(path.read_bytes(),payload)
                    self.assertEqual(store.health()['published'],0)
                finally:store.close()

    def test_pdf_comparison_opt_in_cannot_skip_annex_names_other_duplicates_or_cap(self):
        url='https://www.jlrd.gov.cn/jlsjk/202608/example.html'
        head='<div class="bt">测试条例</div><span id="zdztText">吉林省人大常委会</span>'
        variants=[(('a.docx','测试条例.docx'),('b.docx','测试条例.docx')),
                  (('a.pdf','测试条例.pdf'),('b.pdf','附件一.pdf')),
                  tuple((f'{n}.pdf','测试条例.pdf') for n in range(4))]
        for links in variants:
            body=head+''.join(f'<a href="{url}">{label}</a>' for url,label in links)
            with self.subTest(links=links),self.assertRaises(ValueError):
                jilin_sources.detail_attachments(body.encode(),url,'测试条例','吉林省人大常委会',compare_duplicate_pdfs=True)

    def test_selected_pdf_compares_three_copies_and_retains_uncompared_word(self):
        from test_official_pdf import pdf
        payload=pdf()
        sample={'id':'127','title':'Test Law','url':'https://www.jlrd.gov.cn/jlsjk/202608/example.html',
                'issuer':'吉林省人大常委会','region_name':'吉林省','kind':'local_regulation','preferred_format':'pdf'}
        detail='<div class="bt">Test Law</div><span id="zdztText">吉林省人大常委会</span>'+''.join(f'<a href="{name}">Test Law.{name.rsplit(".",1)[1]}</a>' for name in ('a.pdf','b.pdf','c.pdf','d.docx'))
        calls=[]
        def fetch(url):
            calls.append(url)
            if url.endswith('/robots.txt'):return page(url,'',404)
            if url.endswith('.pdf'):return Response(url=url,content=payload,status=200,reason='test',cookies={},headers={},request_headers={})
            if url.endswith('.docx'):raise AssertionError('不得声称已读取未比对Word')
            return page(url,detail)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=LegalStore(root/'data/legal.sqlite3')
            try:
                row=ingest_sample(root,sample,PublicReader(fetch=fetch,delay=0),store)
                self.assertEqual(row['status'],'ingested_quarantine')
                self.assertEqual(len(row['compared_pdf_originals']),3)
                self.assertEqual(len([url for url in calls if url.endswith('.pdf')]),3)
                self.assertEqual(row['uncompared_alternative_urls'],[sample['url'].rsplit('/',1)[0]+'/d.docx'])
                self.assertEqual(store.detail(row['version_id'])['provenance']['pages'][0]['page'],1)
            finally:store.close()

    def test_http_error_and_challenge_never_ingest(self):
        for status,body in ((403,'拒绝'),(200,'<title>安全验证</title>captcha')):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                store=LegalStore(root/'data/legal.sqlite3')
                def fetch(url):
                    return page(url,'',404) if url.endswith('/robots.txt') else page(url,body,status)
                row=ingest_sample(root,self.sample,PublicReader(fetch=fetch,delay=0),store)
                self.assertEqual(row['status'],'failed')
                self.assertEqual(store.health()['versions'],0)
                store.close()

    def test_html_original_and_body_roundtrip_are_quarantine_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=LegalStore(root/'data/legal.sqlite3')
            def fetch(url):
                return page(url,'',404) if url.endswith('/robots.txt') else page(url,self.body)
            reader=PublicReader(fetch=fetch,delay=0)
            first=ingest_sample(root,self.sample,reader,store)
            second=ingest_sample(root,self.sample,reader,store)
            self.assertEqual(first['status'],'ingested_quarantine')
            self.assertEqual(first['version_id'],second['version_id'])
            self.assertEqual(store.health()['versions'],1)
            self.assertEqual(store.health()['published'],0)
            self.assertEqual(store.detail(first['version_id'])['region'],'CN-JL')
            self.assertEqual(hashlib.sha256((root/first['original_path']).read_bytes()).hexdigest(),first['original_sha256'])
            store.close()
