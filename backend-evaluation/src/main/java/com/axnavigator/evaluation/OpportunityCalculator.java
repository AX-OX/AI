package com.axnavigator.evaluation;

import java.time.LocalDate;
import java.time.YearMonth;
import java.util.*;

/** 사용자 첨부 제안의 자체 수식. 컨설팅 기관의 인증된 점수가 아니다. */
public final class OpportunityCalculator {
    public static final String VERSION = "ax-opportunity-v1";
    public record Metric(LocalDate start, LocalDate end, long count, double minutes, long hourlyCost, Double errorRate, String source) {}
    public record Process(long id, long departmentId, String name, double standardization, boolean requiresApproval, String exceptions) {}
    public record SystemInfo(long id, boolean api, String access) {}
    public record Solution(long id, long buildCost, long monthlyRunCost, double[] automation, double[] reduction, String source) {}
    public record Candidate(long processId, long solutionId) {}

    private static void range(double n, double min, double max, String field) {
        if (!Double.isFinite(n) || n < min || n > max) throw new IllegalArgumentException(field + " 범위 오류");
    }
    private static double round(double value) { return Math.round(value * 100.0) / 100.0; }
    public static int confidence(String source) {
        return switch (source) { case "MEASURED" -> 100; case "SURVEY" -> 60; case "ASSUMED" -> 20; default -> throw new IllegalArgumentException("알 수 없는 data_source"); };
    }
    public static Map<String,Object> calculate(Process process, Solution solution, List<Metric> metrics, List<SystemInfo> systems, LocalDate asOf) {
        range(process.standardization(),0,1,"standardization_level");
        if (solution.buildCost() < 0 || solution.monthlyRunCost() < 0 || solution.automation().length != 3 || solution.reduction().length != 3) throw new IllegalArgumentException("솔루션 비용·시나리오 오류");
        var expected = Set.of(YearMonth.from(asOf).minusMonths(1),YearMonth.from(asOf).minusMonths(2),YearMonth.from(asOf).minusMonths(3));
        var selected = metrics.stream().filter(m -> expected.contains(YearMonth.from(m.start()))).toList();
        if (selected.size()!=3 || selected.stream().map(m -> YearMonth.from(m.start())).distinct().count()!=3) throw new IllegalArgumentException("직전 완료 월 3개 지표가 필요합니다");
        double hours=0, labor=0, weightedErrors=0; long count=0; int dataConfidence=100; boolean hasAllErrorRates=true;
        for(var m:selected) {
            var month=YearMonth.from(m.start());
            if (!m.start().equals(month.atDay(1)) || !m.end().equals(month.atEndOfMonth()) || m.count()<0 || m.hourlyCost()<0) throw new IllegalArgumentException("월 지표 범위 오류");
            range(m.minutes(),0,1e9,"avg_processing_minutes"); if(m.errorRate()!=null) range(m.errorRate(),0,1,"error_rate"); else hasAllErrorRates=false;
            hours+=m.count()*m.minutes()/60.0; labor+=m.count()*m.minutes()/60.0*m.hourlyCost();
            if(m.errorRate()!=null) weightedErrors+=m.count()*m.errorRate(); count+=m.count(); dataConfidence=Math.min(dataConfidence,confidence(m.source()));
        }
        if (count==0 || hours==0) throw new IllegalArgumentException("기준 처리량·시간이 부족합니다");
        // 월별 시간·단가 변동을 보존: 3개월 합 × 4. 평균 건당 시간은 처리량 가중평균.
        double annualHours=hours*4, annualLabor=labor*4;
        long run=Math.multiplyExact(solution.monthlyRunCost(),12), cost=Math.addExact(solution.buildCost(),run);
        if (cost<=0) throw new IllegalArgumentException("초년도 비용은 양수여야 합니다");
        var scenarios=new LinkedHashMap<String,Object>(); String[] names={"low","base","high"};
        for(int i=0;i<3;i++) {
            range(solution.automation()[i],0,1,"automation_rate"); range(solution.reduction()[i],0,1,"time_reduction_rate");
            double fraction=solution.automation()[i]*solution.reduction()[i];
            double saved=annualHours*fraction, value=annualLabor*fraction;
            var scenario=new LinkedHashMap<String,Object>();
            scenario.put("annual_saved_hours",round(saved)); scenario.put("annual_saving_krw",Math.round(value));
            scenario.put("roi_pct",round((value-cost)/cost*100));
            scenario.put("payback_months",value>run ? round(12.0*solution.buildCost()/(value-run)):null);
            scenario.put("automation_rate",solution.automation()[i]); scenario.put("time_reduction_rate",solution.reduction()[i]);
            scenarios.put(names[i],scenario);
        }
        double baseHours=annualHours*solution.automation()[1]*solution.reduction()[1];
        boolean api=systems.stream().anyMatch(SystemInfo::api);
        String risk=systems.isEmpty() || systems.stream().anyMatch(s -> s.access().equals("NONE")) ? "DATA_ACCESS_BLOCKED"
            : process.requiresApproval() || process.exceptions()!=null && !process.exceptions().isBlank() ? "REVIEW_REQUIRED" : "ELIGIBLE";
        double impact=Math.min(100,baseHours/2000*100), feasibility=process.standardization()*60+(api?40:0);
        var scores=new LinkedHashMap<String,Object>();
        scores.put("impact_score",round(impact)); scores.put("feasibility_score",round(feasibility)); scores.put("confidence_score",dataConfidence);
        scores.put("ax_score",round(impact*.50+feasibility*.35+dataConfidence*.15));
        scores.put("weights",Map.of("impact_score",.50,"feasibility_score",.35,"confidence_score",.15));
        scores.put("impact_normalization_hours",2000);
        scores.put("confidence_scores",Map.of("MEASURED",100,"SURVEY",60,"ASSUMED",20)); scores.put("risk_status",risk);
        scores.put("poc_required", dataConfidence<100 || !"MEASURED".equals(solution.source()));
        var warnings=new ArrayList<String>();
        if(dataConfidence<100) warnings.add("LOW_DATA_CONFIDENCE");
        if(!"MEASURED".equals(solution.source())) warnings.add("CATALOG_EFFECT_NOT_MEASURED");
        if(annualLabor*solution.automation()[1]*solution.reduction()[1]<cost) warnings.add("NEGATIVE_FIRST_YEAR_ROI");
        scores.put("warnings",warnings); scores.put("criteria_version",VERSION);
        var baseline=new LinkedHashMap<String,Object>();
        baseline.put("monthly_count",round(count/3.0)); baseline.put("avg_processing_minutes",round(hours*60/count));
        baseline.put("annual_hours",round(annualHours)); baseline.put("hourly_labor_cost_krw",round(labor/hours));
        baseline.put("error_rate",hasAllErrorRates?weightedErrors/count:null); baseline.put("api_available",api); baseline.put("standardization_level",process.standardization());
        baseline.put("aggregation_basis", "직전 완료 월 3개 / 처리량·시간 가중");
        baseline.put("periods",selected.stream().map(m->m.start().toString()).sorted().toList());
        baseline.put("data_sources",selected.stream().map(Metric::source).distinct().sorted().toList());
        baseline.put("system_ids",systems.stream().map(SystemInfo::id).toList()); baseline.put("exception_rules",process.exceptions());
        var result=new LinkedHashMap<String,Object>();
        result.put("process_id",process.id()); result.put("solution_id",solution.id()); result.put("first_year_cost_krw",cost);
        result.put("annual_run_cost_krw",run); result.put("build_cost_krw",solution.buildCost()); result.put("baseline",baseline);
        result.put("scenarios",scenarios); result.put("opportunity",scores);
        result.put("assumptions",List.of("자체 설계 가중치 50/35/15, 정규화 기준 2000시간", "인력시간 환산 가치이며 확정 현금 절감이 아님", "솔루션 가정 출처: "+solution.source(), "API 유무는 기술적 실현 가능성의 대리 지표", "혼합 지표 출처는 최저 신뢰도 적용"));
        return result;
    }
    @SuppressWarnings("unchecked")
    private static double score(Map<String,Object> r) { return ((Number)((Map<String,Object>)r.get("opportunity")).get("ax_score")).doubleValue(); }
    @SuppressWarnings("unchecked")
    public static Map<String,Object> portfolio(List<Map<String,Object>> evaluated,long budget,int size) {
        if (size<1 || size>10 || evaluated.size()>10 || budget<0) throw new IllegalArgumentException("후보·예산 범위 오류");
        var eligible=evaluated.stream().filter(r->!((Map<String,Object>)r.get("opportunity")).get("risk_status").equals("DATA_ACCESS_BLOCKED"))
            .sorted(Comparator.<Map<String,Object>>comparingDouble(OpportunityCalculator::score).reversed()
                .thenComparingLong(r->((Number)r.get("process_id")).longValue()).thenComparingLong(r->((Number)r.get("solution_id")).longValue())).toList();
        List<Map<String,Object>> best=List.of(); double bestScore=-1; long bestCost=Long.MAX_VALUE;
        for(int mask=0;mask<(1<<eligible.size());mask++) {
            if(Integer.bitCount(mask)!=size) continue;
            var combination=new ArrayList<Map<String,Object>>(); var processes=new HashSet<Long>(); long cost=0; double sum=0;
            for(int i=0;i<eligible.size();i++) if((mask&(1<<i))!=0) {
                var row=eligible.get(i); processes.add(((Number)row.get("process_id")).longValue()); combination.add(row);
                cost=Math.addExact(cost,((Number)row.get("first_year_cost_krw")).longValue()); sum+=score(row);
            }
            if(processes.size()!=size || cost>budget) continue;
            if(sum>bestScore+1e-9 || Math.abs(sum-bestScore)<1e-9 && cost<bestCost) { best=combination; bestScore=sum; bestCost=cost; }
        }
        return Map.of("items",best,"insufficient",best.isEmpty(),"budget_krw",budget,"total_cost_krw",best.isEmpty()?0:bestCost,"priority_basis",VERSION,"rankings",eligible);
    }
}
