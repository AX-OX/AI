package com.axnavigator.evaluation;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDate;
import java.util.*;
import static com.axnavigator.evaluation.OpportunityCalculator.*;

/** 팀 Backend에 통합할 조회·평가 모듈. 로그인·승인·저장 API는 기존 Backend 책임이다. */
@RestController
@RequestMapping("/internal")
public class EvaluationController {
    private final JdbcTemplate db;
    private final ObjectMapper json;
    private final String token;
    private final long company;
    private final LocalDate asOf;
    public EvaluationController(JdbcTemplate db,ObjectMapper json,@Value("${ax.internal-token}")String token,
        @Value("${ax.company-id}")long company,@Value("${ax.reference-date}")String date) {
        if(token.isBlank()) throw new IllegalArgumentException("INTERNAL_TOKEN 필수");
        this.db=db;this.json=json;this.token=token;this.company=company;this.asOf=date.isBlank()?LocalDate.now():LocalDate.parse(date);
    }
    private void auth(String supplied) {
        if(supplied==null || !MessageDigest.isEqual(supplied.getBytes(StandardCharsets.UTF_8),token.getBytes(StandardCharsets.UTF_8))) throw new ResponseStatusException(HttpStatus.FORBIDDEN);
    }
    private void scope(long id) { if(id!=company) throw new ResponseStatusException(HttpStatus.FORBIDDEN,"회사 범위 오류"); }
    private Map<String,Object> one(String sql,Object...args) {
        var rows=db.queryForList(sql,args); if(rows.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND,"데이터 없음"); return rows.getFirst();
    }
    private List<Map<String,Object>> processes(long id,Long department) {
        scope(id);
        var rows=db.queryForList("SELECT p.* FROM business_processes p JOIN departments d USING(department_id) WHERE d.company_id=? AND (?::bigint IS NULL OR d.department_id=?) ORDER BY p.process_id",id,department,department);
        for(var row:rows) try { row.put("process_steps",json.readValue(row.get("process_steps").toString(),List.class)); } catch(Exception e) { throw new IllegalArgumentException("process_steps JSON 오류"); }
        return rows;
    }
    @GetMapping("/companies/{id}")
    Map<String,Object> company(@RequestHeader(value="X-Internal-Token",required=false)String t,@PathVariable long id) {
        auth(t);scope(id);var result=one("SELECT * FROM companies WHERE company_id=?",id);
        result.put("departments",db.queryForList("SELECT department_id,company_id,department_name FROM departments WHERE company_id=? ORDER BY department_id",id));return result;
    }
    @GetMapping("/companies/{id}/processes")
    List<Map<String,Object>> listProcesses(@RequestHeader(value="X-Internal-Token",required=false)String t,@PathVariable long id,@RequestParam(required=false)Long departmentId) {
        auth(t);return processes(id,departmentId);
    }
    @GetMapping("/companies/{id}/metrics")
    List<Map<String,Object>> metrics(@RequestHeader(value="X-Internal-Token",required=false)String t,@PathVariable long id,@RequestParam(required=false)Long departmentId) {
        auth(t);scope(id);return db.queryForList("SELECT m.* FROM process_metrics m JOIN business_processes p USING(process_id) JOIN departments d USING(department_id) WHERE d.company_id=? AND (?::bigint IS NULL OR d.department_id=?) AND m.period_start>=date_trunc('month',?::date)-interval '3 months' AND m.period_end<date_trunc('month',?::date) ORDER BY m.process_id,m.period_start",id,departmentId,departmentId,asOf,asOf);
    }
    @GetMapping("/companies/{id}/budget")
    Map<String,Object> budget(@RequestHeader(value="X-Internal-Token",required=false)String t,@PathVariable long id) { auth(t);scope(id);return one("SELECT company_id,ax_budget_krw FROM companies WHERE company_id=?",id); }
    @GetMapping("/companies/{id}/systems")
    Map<String,Object> systems(@RequestHeader(value="X-Internal-Token",required=false)String t,@PathVariable long id) {
        auth(t);scope(id);return Map.of("systems",db.queryForList("SELECT * FROM it_systems WHERE company_id=? ORDER BY system_id",id),"process_systems",db.queryForList("SELECT ps.* FROM process_systems ps JOIN it_systems s USING(system_id) JOIN business_processes p USING(process_id) JOIN departments d USING(department_id) WHERE s.company_id=? AND d.company_id=? ORDER BY ps.process_id,ps.system_id",id,id));
    }
    @GetMapping("/solutions")
    List<Map<String,Object>> solutions(@RequestHeader(value="X-Internal-Token",required=false)String t) { auth(t);return db.queryForList("SELECT * FROM ai_solution_catalog ORDER BY solution_id"); }
    private static double num(Map<String,Object> r,String field) { Object v=r.get(field); if(!(v instanceof Number)) throw new IllegalArgumentException("지표 부족: "+field);return ((Number)v).doubleValue(); }
    private Map<String,Object> calculate(long processId,long solutionId) {
        var p=one("SELECT p.* FROM business_processes p JOIN departments d USING(department_id) WHERE p.process_id=? AND d.company_id=?",processId,company);
        var s=one("SELECT * FROM ai_solution_catalog WHERE solution_id=?",solutionId);
        var metrics=db.query("SELECT * FROM process_metrics WHERE process_id=?",(r,n)->new Metric(r.getDate("period_start").toLocalDate(),r.getDate("period_end").toLocalDate(),r.getLong("processing_count"),r.getDouble("avg_processing_minutes"),r.getLong("hourly_labor_cost_krw"),(r.getObject("error_rate")==null ? null : ((Number)r.getObject("error_rate")).doubleValue()),r.getString("data_source")),processId);
        var systems=db.query("SELECT s.* FROM it_systems s JOIN process_systems ps USING(system_id) WHERE ps.process_id=? AND s.company_id=?",(r,n)->new SystemInfo(r.getLong("system_id"),r.getBoolean("api_available"),r.getString("data_access_level")),processId,company);
        var solution=new Solution(solutionId,((Number)s.get("base_build_cost_krw")).longValue(),((Number)s.get("monthly_run_cost_krw")).longValue(),new double[]{num(s,"automation_rate_low"),num(s,"automation_rate_base"),num(s,"automation_rate_high")},new double[]{num(s,"time_reduction_rate_low"),num(s,"time_reduction_rate_base"),num(s,"time_reduction_rate_high")},s.get("data_source").toString());
        return OpportunityCalculator.calculate(new OpportunityCalculator.Process(processId,((Number)p.get("department_id")).longValue(),p.get("process_name").toString(),num(p,"standardization_level"),(Boolean)p.get("requires_approval"),(String)p.get("exception_rules")),solution,metrics,systems,asOf);
    }
    public record RoiRequest(long processId,long solutionId) {}
    public record Pair(long processId,long solutionId) {}
    public record PortfolioRequest(long companyId,List<Pair> candidates,int maxItems) {}
    @PostMapping({"/ax/roi","/ax/opportunity"})
    Map<String,Object> roi(@RequestHeader(value="X-Internal-Token",required=false)String t,@RequestBody RoiRequest body) { auth(t);return calculate(body.processId(),body.solutionId()); }
    @PostMapping("/ax/portfolio")
    Map<String,Object> portfolio(@RequestHeader(value="X-Internal-Token",required=false)String t,@RequestBody PortfolioRequest body) {
        auth(t);scope(body.companyId());if(body.candidates()==null || body.candidates().isEmpty() || body.candidates().size()>10 || body.candidates().stream().distinct().count()!=body.candidates().size()) throw new IllegalArgumentException("후보는 중복 없이 1~10개");
        var budget=((Number)one("SELECT ax_budget_krw FROM companies WHERE company_id=?",company).get("ax_budget_krw")).longValue();
        return OpportunityCalculator.portfolio(body.candidates().stream().map(c->calculate(c.processId(),c.solutionId())).toList(),budget,body.maxItems());
    }
    @ExceptionHandler(IllegalArgumentException.class)
    @ResponseStatus(HttpStatus.UNPROCESSABLE_ENTITY)
    Map<String,Object> invalid(IllegalArgumentException e) { return Map.of("code","INSUFFICIENT_DATA","message",e.getMessage()); }
}
