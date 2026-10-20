package com.axnavigator.evaluation;
import org.junit.jupiter.api.Test;
import java.time.LocalDate;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static com.axnavigator.evaluation.OpportunityCalculator.*;
class OpportunityCalculatorTest {
    List<Metric> metrics(String source) {
        var rows=new ArrayList<Metric>();
        for(int month=7;month<=9;month++) rows.add(new Metric(LocalDate.of(2026,month,1),LocalDate.of(2026,month,1).withDayOfMonth(month==9?30:31),1000,12,30000,.02,source));
        return rows;
    }
    Map<String,Object> evaluate(List<SystemInfo> systems,String exceptions) {
        return calculate(new OpportunityCalculator.Process(1,1,"test",.8,false,exceptions),new Solution(2,10_000_000,100_000,new double[]{.4,.5,.6},new double[]{.3,.4,.5},"ASSUMED"),metrics("ASSUMED"),systems,LocalDate.of(2026,10,20));
    }
    @Test @SuppressWarnings("unchecked") void exactExampleAndSeparateRoi() {
        var value=evaluate(List.of(new SystemInfo(1,true,"OPEN")),"");
        var scores=(Map<String,Object>)value.get("opportunity");
        assertEquals(24.0,scores.get("impact_score")); // 2400 * .5 * .4 = 480h; 480/2000*100
        assertEquals(88.0,scores.get("feasibility_score")); assertEquals(20,scores.get("confidence_score"));
        assertEquals(45.8,scores.get("ax_score")); assertEquals("ELIGIBLE",scores.get("risk_status"));
        var base=(Map<String,Object>)((Map<String,Object>)value.get("scenarios")).get("base");
        assertEquals(480.0,base.get("annual_saved_hours"));assertEquals(14_400_000L,base.get("annual_saving_krw"));
        assertEquals(28.57,base.get("roi_pct"));
    }
    @Test @SuppressWarnings("unchecked") void blockedExcludedReviewRetained() {
        var blocked=evaluate(List.of(new SystemInfo(1,true,"NONE")),"");
        assertEquals("DATA_ACCESS_BLOCKED",((Map<String,Object>)blocked.get("opportunity")).get("risk_status"));
        assertEquals(true,portfolio(List.of(blocked),1_000_000_000,1).get("insufficient"));
        var review=evaluate(List.of(new SystemInfo(1,true,"OPEN")),"담당자 확인");
        assertEquals("REVIEW_REQUIRED",((Map<String,Object>)review.get("opportunity")).get("risk_status"));
        assertEquals(false,portfolio(List.of(review),1_000_000_000,1).get("insufficient"));
    }
    @Test void missingMonthAndUnknownSourceRejected() {
        assertThrows(IllegalArgumentException.class,()->calculate(new OpportunityCalculator.Process(1,1,"x",.8,false,""),new Solution(2,1,1,new double[]{.5,.5,.5},new double[]{.5,.5,.5},"ASSUMED"),metrics("ASSUMED").subList(0,2),List.of(),LocalDate.of(2026,10,20)));
        assertThrows(IllegalArgumentException.class,()->confidence("UNKNOWN"));
    }
    @Test @SuppressWarnings("unchecked") void budgetAndDuplicateProcess() {
        var value=evaluate(List.of(new SystemInfo(1,true,"OPEN")),"");
        assertEquals(true,portfolio(List.of(value),1,1).get("insufficient"));
        assertEquals(true,portfolio(List.of(value,value),1_000_000_000,2).get("insufficient"));
    }
    @Test @SuppressWarnings("unchecked") void mixedSourcesAndMonthlyWeightedCosts() {
        var rows=List.of(new Metric(LocalDate.of(2026,7,1),LocalDate.of(2026,7,31),1000,12,30000,.01,"MEASURED"),
                         new Metric(LocalDate.of(2026,8,1),LocalDate.of(2026,8,31),2000,6,60000,.02,"SURVEY"),
                         new Metric(LocalDate.of(2026,9,1),LocalDate.of(2026,9,30),1000,12,30000,.03,"ASSUMED"));
        var value=calculate(new OpportunityCalculator.Process(1,1,"test",.8,false,""),new Solution(2,10_000_000,100_000,new double[]{.4,.5,.6},new double[]{.3,.4,.5},"ASSUMED"),rows,List.of(new SystemInfo(1,true,"OPEN")),LocalDate.of(2026,10,20));
        assertEquals(20,((Map<String,Object>)value.get("opportunity")).get("confidence_score"));
        var base=(Map<String,Object>)((Map<String,Object>)value.get("scenarios")).get("base");
        assertEquals(19_200_000L,base.get("annual_saving_krw"));
    }
    @Test @SuppressWarnings("unchecked") void noSavingsDoesNotInventPayback() {
        var value=calculate(new OpportunityCalculator.Process(1,1,"test",.8,false,""),new Solution(2,10_000_000,100_000,new double[]{0,0,0},new double[]{.3,.4,.5},"ASSUMED"),metrics("ASSUMED"),List.of(new SystemInfo(1,true,"OPEN")),LocalDate.of(2026,10,20));
        var base=(Map<String,Object>)((Map<String,Object>)value.get("scenarios")).get("base");
        assertNull(base.get("payback_months")); assertEquals(-100.0,base.get("roi_pct"));
    }
}
