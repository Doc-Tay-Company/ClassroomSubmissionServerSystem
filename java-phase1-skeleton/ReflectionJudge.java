import java.io.File;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * ReflectionJudge - Harness tin cay de cham bai Java bang Reflection.
 *
 * Cach chay (do Python runner goi, khong chay tay trong server):
 *   javac -d judge_out ReflectionJudge.java
 *   java -Xmx256m -cp judge_out ReflectionJudge <thu-muc-out-cua-sinh-vien> < spec.json
 *
 * Input:  JSON spec qua stdin. Chi chua cac check can chay trong lan nay.
 *         Pretest: Python runner loc truoc, chi dua check is_visible=true.
 *         Cham cuoi: dua toan bo check (visible + hidden).
 * Output: JSON ket qua ra stdout, khong in gi khac ra stdout.
 *
 * Luu y an toan (xem dac ta Phase 1):
 * - Judge chay trong JVM rieng, khong phai process cua server Python.
 * - Code sinh vien chi duoc load bang URLClassLoader rieng, parent la
 *   platform classloader, nen khong thay duoc class cua judge.
 * - Timeout, gioi han RAM (-Xmx), thu muc tam rieng do Python runner dam nhan.
 * - Judge KHONG phai sandbox tuyet doi: muon chan triet de doc file / mang
 *   thi can container (--network none) o phase sau.
 */
public class ReflectionJudge {

    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.out.println("{\"error\":\"missing student output dir argument\"}");
            System.exit(2);
            return;
        }
        String studentDir = args[0];
        String input = new String(System.in.readAllBytes(), StandardCharsets.UTF_8);
        if (input == null || input.trim().isEmpty()) {
            System.out.println("{\"error\":\"empty spec on stdin\"}");
            System.exit(2);
            return;
        }

        Object parsed;
        try {
            parsed = new JsonParser(input).parseValue();
        } catch (Exception e) {
            System.out.println("{\"error\":\"invalid spec JSON: " + Json.escape(e.getMessage()) + "\"}");
            System.exit(2);
            return;
        }
        if (!(parsed instanceof Map)) {
            System.out.println("{\"error\":\"spec root must be an object\"}");
            System.exit(2);
            return;
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> spec = (Map<String, Object>) parsed;
        String targetClassName = getString(spec, "target_class", "");
        @SuppressWarnings("unchecked")
        List<Object> checks = (List<Object>) spec.getOrDefault("checks", new ArrayList<>());

        Class<?> targetClass = null;
        String loadError = null;
        URLClassLoader loader = null;
        try {
            File dir = new File(studentDir);
            URL[] urls = new URL[]{dir.toURI().toURL()};
            loader = new URLClassLoader(urls, ClassLoader.getPlatformClassLoader());
            targetClass = Class.forName(targetClassName, true, loader);
        } catch (Throwable t) {
            loadError = t.getClass().getName() + ": " + String.valueOf(t.getMessage());
        }

        List<Map<String, Object>> results = new ArrayList<>();
        int totalPoints = 0;
        int score = 0;

        for (Object checkObj : checks) {
            long start = System.nanoTime();
            @SuppressWarnings("unchecked")
            Map<String, Object> check = checkObj instanceof Map
                    ? (Map<String, Object>) checkObj : new LinkedHashMap<>();
            String id = getString(check, "id", "");
            String kind = getString(check, "kind", "");
            int points = getInt(check, "points", 0);
            totalPoints += points;

            boolean passed = false;
            String expected = "";
            String actual = "";
            String error = null;
            try {
                if (targetClass == null) {
                    throw new RuntimeException("Class not found: " + targetClassName
                            + (loadError != null ? " (" + loadError + ")" : ""));
                }
                CheckOutcome out = runCheck(targetClass, loader, check);
                passed = out.passed;
                expected = out.expected;
                actual = out.actual;
                if (out.error != null) {
                    error = out.error;
                }
            } catch (Throwable t) {
                passed = false;
                error = t.getClass().getSimpleName() + ": " + String.valueOf(t.getMessage());
                if (expected.isEmpty()) {
                    expected = "check passes";
                }
                if (actual.isEmpty()) {
                    actual = "check failed with error";
                }
            }
            int earned = passed ? points : 0;
            score += earned;
            long timeMs = (System.nanoTime() - start) / 1_000_000L;

            Map<String, Object> r = new LinkedHashMap<>();
            r.put("id", id);
            r.put("kind", kind);
            r.put("passed", passed);
            r.put("points", points);
            r.put("points_earned", earned);
            r.put("expected", expected);
            r.put("actual", actual);
            r.put("error", error);
            r.put("time_ms", timeMs);
            results.add(r);
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("target_class", targetClassName);
        out.put("score", score);
        out.put("total_points", totalPoints);
        out.put("checks", results);
        System.out.println(Json.stringify(out));
        if (loader != null) {
            try { loader.close(); } catch (Exception ignored) { }
        }
    }

    // ---------------- Check dispatch ----------------

    private static class CheckOutcome {
        boolean passed;
        String expected = "";
        String actual = "";
        String error = null;
        CheckOutcome(boolean p, String e, String a) { passed = p; expected = e; actual = a; }
        CheckOutcome(boolean p, String e, String a, String err) { passed = p; expected = e; actual = a; error = err; }
    }

    private static CheckOutcome runCheck(Class<?> clazz, ClassLoader loader,
                                         Map<String, Object> check) throws Exception {
        String kind = getString(check, "kind", "");
        switch (kind) {
            case "field": return checkField(clazz, loader, check);
            case "constructor": return checkConstructor(clazz, loader, check);
            case "method": return checkMethod(clazz, loader, check);
            case "implements": return checkImplements(clazz, loader, check);
            case "behavior": return checkBehavior(clazz, loader, check);
            case "toString": return checkToString(clazz, loader, check);
            case "comparable": return checkComparable(clazz, loader, check);
            default:
                return new CheckOutcome(false, "known check kind",
                        "unknown kind: " + kind, "unknown check kind: " + kind);
        }
    }

    private static CheckOutcome checkField(Class<?> clazz, ClassLoader loader,
                                           Map<String, Object> check) throws Exception {
        String fieldName = getString(check, "field_name", "");
        String expectedType = getString(check, "expected_type", "");
        @SuppressWarnings("unchecked")
        List<Object> expectedMods = (List<Object>) check.getOrDefault("expected_modifiers", new ArrayList<>());
        Field f;
        try {
            f = clazz.getDeclaredField(fieldName);
        } catch (NoSuchFieldException e) {
            return new CheckOutcome(false,
                    describeModifiers(expectedMods) + " " + expectedType + " " + fieldName,
                    "field not found: " + fieldName);
        }
        String expected = describeModifiers(expectedMods) + " " + expectedType + " " + fieldName;
        String actual = Modifier.toString(f.getModifiers()) + " " + f.getType().getName() + " " + f.getName();
        boolean typeOk = typeMatches(expectedType, f.getType(), loader);
        List<String> missing = missingModifiers(f.getModifiers(), expectedMods);
        boolean ok = typeOk && missing.isEmpty();
        String err = null;
        if (!typeOk) err = "type mismatch";
        if (!missing.isEmpty()) err = "missing modifiers: " + String.join(", ", missing);
        return new CheckOutcome(ok, expected, actual, err);
    }

    private static CheckOutcome checkConstructor(Class<?> clazz, ClassLoader loader,
                                                 Map<String, Object> check) throws Exception {
        @SuppressWarnings("unchecked")
        List<Object> paramNames = (List<Object>) check.getOrDefault("param_types", new ArrayList<>());
        Class<?>[] params = resolveTypes(paramNames, loader);
        @SuppressWarnings("unchecked")
        List<Object> expectedMods = (List<Object>) check.getOrDefault("expected_modifiers", new ArrayList<>());
        String expected = describeModifiers(expectedMods) + " " + clazz.getSimpleName()
                + "(" + joinTypeNames(params) + ")";
        Constructor<?> c;
        try {
            c = clazz.getDeclaredConstructor(params);
        } catch (NoSuchMethodException e) {
            return new CheckOutcome(false, expected,
                    "constructor not found: " + clazz.getSimpleName() + "(" + joinTypeNames(params) + ")");
        }
        String actual = Modifier.toString(c.getModifiers()) + " " + clazz.getSimpleName()
                + "(" + joinTypeNames(c.getParameterTypes()) + ")";
        List<String> missing = missingModifiers(c.getModifiers(), expectedMods);
        return new CheckOutcome(missing.isEmpty(), expected, actual,
                missing.isEmpty() ? null : "missing modifiers: " + String.join(", ", missing));
    }

    private static CheckOutcome checkMethod(Class<?> clazz, ClassLoader loader,
                                            Map<String, Object> check) throws Exception {
        String methodName = getString(check, "method_name", "");
        @SuppressWarnings("unchecked")
        List<Object> paramNames = (List<Object>) check.getOrDefault("param_types", new ArrayList<>());
        Class<?>[] params = resolveTypes(paramNames, loader);
        String expectedReturn = getString(check, "expected_return_type", "");
        @SuppressWarnings("unchecked")
        List<Object> expectedMods = (List<Object>) check.getOrDefault("expected_modifiers", new ArrayList<>());
        String expected = describeModifiers(expectedMods) + " " + expectedReturn + " "
                + methodName + "(" + joinTypeNames(params) + ")";
        Method m;
        try {
            m = clazz.getDeclaredMethod(methodName, params);
        } catch (NoSuchMethodException e) {
            return new CheckOutcome(false, expected,
                    "method not found: " + methodName + "(" + joinTypeNames(params) + ")");
        }
        String actual = Modifier.toString(m.getModifiers()) + " " + m.getReturnType().getName()
                + " " + m.getName() + "(" + joinTypeNames(m.getParameterTypes()) + ")";
        boolean returnOk = expectedReturn.isEmpty() || typeMatches(expectedReturn, m.getReturnType(), loader);
        List<String> missing = missingModifiers(m.getModifiers(), expectedMods);
        boolean ok = returnOk && missing.isEmpty();
        String err = null;
        if (!returnOk) err = "return type mismatch";
        if (!missing.isEmpty()) err = "missing modifiers: " + String.join(", ", missing);
        return new CheckOutcome(ok, expected, actual, err);
    }

    private static CheckOutcome checkImplements(Class<?> clazz, ClassLoader loader,
                                                Map<String, Object> check) throws Exception {
        String ifaceName = getString(check, "expected_interface", "");
        Class<?> iface = resolveType(ifaceName, loader);
        String expected = "implements " + ifaceName;
        boolean ok = iface != null && iface.isAssignableFrom(clazz);
        String actual = ok ? "implements " + ifaceName : "does not implement " + ifaceName;
        return new CheckOutcome(ok, expected, actual, ok ? null : "interface not implemented");
    }

    private static CheckOutcome checkBehavior(Class<?> clazz, ClassLoader loader,
                                              Map<String, Object> check) throws Exception {
        @SuppressWarnings("unchecked")
        Map<String, Object> setup = (Map<String, Object>) check.getOrDefault("setup", new LinkedHashMap<>());
        Object target = createObject(clazz, loader, setup);
        @SuppressWarnings("unchecked")
        Map<String, Object> invoke = (Map<String, Object>) check.getOrDefault("invoke", new LinkedHashMap<>());
        String methodName = getString(invoke, "method", "");
        @SuppressWarnings("unchecked")
        List<Object> argsJson = (List<Object>) invoke.getOrDefault("args", new ArrayList<>());
        @SuppressWarnings("unchecked")
        List<Object> paramNames = (List<Object>) invoke.getOrDefault("param_types", new ArrayList<>());

        Method m = findMethod(clazz, loader, methodName, paramNames, argsJson.size());
        if (m == null) {
            return new CheckOutcome(false, "method " + methodName + " exists",
                    "method not found: " + methodName);
        }
        m.setAccessible(true);
        Object[] args = convertAll(argsJson, m.getParameterTypes());
        Object returned = null;
        Throwable thrown = null;
        try {
            returned = m.invoke(target, args);
        } catch (InvocationTargetException e) {
            thrown = e.getCause() != null ? e.getCause() : e;
        }

        String expectException = getString(check, "expect_exception", "");
        if (!expectException.isEmpty()) {
            String expected = "throws " + expectException;
            if (thrown == null) {
                return new CheckOutcome(false, expected, "no exception, returned: " + String.valueOf(returned));
            }
            String actualName = thrown.getClass().getName();
            String actualSimple = thrown.getClass().getSimpleName();
            boolean ok = actualName.equals(expectException) || actualSimple.equals(expectException);
            return new CheckOutcome(ok, expected, "threw " + actualName + ": " + String.valueOf(thrown.getMessage()),
                    ok ? null : "wrong exception type");
        }
        if (thrown != null) {
            return new CheckOutcome(false, "no exception",
                    "threw " + thrown.getClass().getName() + ": " + String.valueOf(thrown.getMessage()));
        }

        // expect_state: {"getGpa": 9.0} hoac {"gpa": 9.0}
        if (check.containsKey("expect_state") && check.get("expect_state") instanceof Map) {
            @SuppressWarnings("unchecked")
            Map<String, Object> state = (Map<String, Object>) check.get("expect_state");
            for (Map.Entry<String, Object> e : state.entrySet()) {
                Object actualValue = readState(target, e.getKey());
                if (!valuesEqual(e.getValue(), actualValue)) {
                    return new CheckOutcome(false,
                            e.getKey() + " = " + Json.stringify(e.getValue()),
                            e.getKey() + " = " + Json.stringify(actualValue));
                }
            }
            return new CheckOutcome(true, "state matches expect_state", "state matches expect_state");
        }

        if (check.containsKey("expect_return")) {
            Object expectedValue = check.get("expect_return");
            boolean ok = valuesEqual(expectedValue, returned);
            return new CheckOutcome(ok,
                    "return " + Json.stringify(expectedValue),
                    "return " + Json.stringify(returned),
                    ok ? null : "return value mismatch");
        }
        // Khong co expect gi: goi thanh cong, khong nem exception la pass.
        return new CheckOutcome(true, "method runs without exception", "method ran without exception");
    }

    private static CheckOutcome checkToString(Class<?> clazz, ClassLoader loader,
                                              Map<String, Object> check) throws Exception {
        @SuppressWarnings("unchecked")
        Map<String, Object> setup = (Map<String, Object>) check.getOrDefault("setup", new LinkedHashMap<>());
        Object target = createObject(clazz, loader, setup);
        String template = getString(check, "expected_template", "");
        String filled = fillTemplate(template, target, clazz);
        String expected = filled;
        String actualRaw = String.valueOf(target.toString());
        // Chi chuan hoa CRLF -> LF, khong trim, khong bo khoang trang (theo quyet dinh da chot).
        String expectedNorm = expected.replace("\r\n", "\n").replace("\r", "\n");
        String actualNorm = actualRaw.replace("\r\n", "\n").replace("\r", "\n");
        boolean ok = expectedNorm.equals(actualNorm);
        return new CheckOutcome(ok, expected, actualRaw, ok ? null : "toString mismatch (exact after template fill)");
    }

    private static CheckOutcome checkComparable(Class<?> clazz, ClassLoader loader,
                                                Map<String, Object> check) throws Exception {
        if (!Comparable.class.isAssignableFrom(clazz)) {
            return new CheckOutcome(false, "implements Comparable",
                    "does not implement Comparable");
        }
        @SuppressWarnings("unchecked")
        List<Object> ctorParamNames = (List<Object>) check.getOrDefault("constructor_param_types", new ArrayList<>());
        @SuppressWarnings("unchecked")
        List<Object> cases = (List<Object>) check.getOrDefault("cases", new ArrayList<>());
        if (cases.isEmpty()) {
            // Dinh dang cu: sort_cases, moi case co a, b, expected_sign
            cases = (List<Object>) check.getOrDefault("sort_cases", new ArrayList<>());
        }
        for (Object caseObj : cases) {
            @SuppressWarnings("unchecked")
            Map<String, Object> c = (Map<String, Object>) caseObj;
            @SuppressWarnings("unchecked")
            List<Object> aArgs = (List<Object>) c.getOrDefault("a", new ArrayList<>());
            @SuppressWarnings("unchecked")
            List<Object> bArgs = (List<Object>) c.getOrDefault("b", new ArrayList<>());
            int expectedSign = getInt(c, "expected_sign", 0);
            Object a = createObjectWithArgs(clazz, loader, ctorParamNames, aArgs);
            Object b = createObjectWithArgs(clazz, loader, ctorParamNames, bArgs);
            @SuppressWarnings("unchecked")
            int cmp = ((Comparable<Object>) a).compareTo(b);
            int sign = Integer.signum(cmp);
            if (sign != expectedSign) {
                return new CheckOutcome(false,
                        "compareTo sign = " + expectedSign,
                        "compareTo sign = " + sign + " (raw " + cmp + ")");
            }
        }
        return new CheckOutcome(true, "all compareTo signs match", "all compareTo signs match");
    }

    // ---------------- Object creation / invocation helpers ----------------

    private static Object createObject(Class<?> clazz, ClassLoader loader,
                                       Map<String, Object> setup) throws Exception {
        @SuppressWarnings("unchecked")
        List<Object> argsJson = (List<Object>) setup.getOrDefault("constructor_args", new ArrayList<>());
        @SuppressWarnings("unchecked")
        List<Object> paramNames = (List<Object>) setup.getOrDefault("constructor_param_types", new ArrayList<>());
        return createObjectWithArgs(clazz, loader, paramNames, argsJson);
    }

    private static Object createObjectWithArgs(Class<?> clazz, ClassLoader loader,
                                               List<Object> paramNames,
                                               List<Object> argsJson) throws Exception {
        if (!paramNames.isEmpty()) {
            Class<?>[] params = resolveTypes(paramNames, loader);
            Constructor<?> c = clazz.getDeclaredConstructor(params);
            c.setAccessible(true);
            Object[] args = convertAll(argsJson, params);
            try {
                return c.newInstance(args);
            } catch (InvocationTargetException e) {
                throw new RuntimeException("constructor threw: "
                        + (e.getCause() != null ? e.getCause().getClass().getName() + ": " + e.getCause().getMessage() : e.getMessage()), e);
            }
        }
        // Khong co param_types: thu tung constructor co cung so luong arg.
        Throwable last = null;
        for (Constructor<?> c : clazz.getDeclaredConstructors()) {
            if (c.getParameterCount() != argsJson.size()) continue;
            try {
                c.setAccessible(true);
                Object[] args = convertAll(argsJson, c.getParameterTypes());
                return c.newInstance(args);
            } catch (InvocationTargetException e) {
                last = e.getCause() != null ? e.getCause() : e;
            } catch (Exception e) {
                last = e;
            }
        }
        if (last != null) {
            throw new RuntimeException("no constructor succeeded, last error: "
                    + last.getClass().getName() + ": " + last.getMessage(), last);
        }
        throw new RuntimeException("no matching constructor for " + argsJson.size() + " args");
    }

    private static Method findMethod(Class<?> clazz, ClassLoader loader,
                                     String name, List<Object> paramNames, int argCount) throws Exception {
        if (!paramNames.isEmpty()) {
            Class<?>[] params = resolveTypes(paramNames, loader);
            try {
                return clazz.getDeclaredMethod(name, params);
            } catch (NoSuchMethodException e) {
                return null;
            }
        }
        for (Method m : clazz.getDeclaredMethods()) {
            if (m.getName().equals(name) && m.getParameterCount() == argCount) {
                return m;
            }
        }
        return null;
    }

    private static Object readState(Object target, String key) throws Exception {
        // Thu getter truoc: getXxx / isXxx, roi moi doc field truc tiep.
        String cap = key.substring(0, 1).toUpperCase() + key.substring(1);
        String[] getterNames = new String[]{"get" + cap, "is" + cap, key};
        for (String g : getterNames) {
            try {
                Method m = target.getClass().getDeclaredMethod(g);
                if (m.getParameterCount() == 0) {
                    m.setAccessible(true);
                    return m.invoke(target);
                }
            } catch (NoSuchMethodException ignored) { }
        }
        Field f = target.getClass().getDeclaredField(key);
        f.setAccessible(true);
        return f.get(target);
    }

    private static String fillTemplate(String template, Object target, Class<?> clazz) throws Exception {
        Matcher matcher = Pattern.compile("\\{([A-Za-z_][A-Za-z0-9_]*)\\}").matcher(template);
        StringBuffer sb = new StringBuffer();
        while (matcher.find()) {
            String fieldName = matcher.group(1);
            Object value = readState(target, fieldName);
            String replacement = value == null ? "null" : String.valueOf(value);
            matcher.appendReplacement(sb, Matcher.quoteReplacement(replacement));
        }
        matcher.appendTail(sb);
        return sb.toString();
    }

    // ---------------- Type / modifier / value helpers ----------------

    private static Class<?> resolveType(String name, ClassLoader loader) throws Exception {
        if (name == null || name.isEmpty()) return null;
        switch (name) {
            case "int": return int.class;
            case "long": return long.class;
            case "double": return double.class;
            case "float": return float.class;
            case "boolean": return boolean.class;
            case "char": return char.class;
            case "byte": return byte.class;
            case "short": return short.class;
            case "void": return void.class;
            case "String": case "java.lang.String": return String.class;
            case "Integer": case "java.lang.Integer": return Integer.class;
            case "Long": case "java.lang.Long": return Long.class;
            case "Double": case "java.lang.Double": return Double.class;
            case "Float": case "java.lang.Float": return Float.class;
            case "Boolean": case "java.lang.Boolean": return Boolean.class;
            case "Character": case "java.lang.Character": return Character.class;
            case "Object": case "java.lang.Object": return Object.class;
            default:
                try {
                    if (loader != null) return Class.forName(name, false, loader);
                } catch (ClassNotFoundException ignored) { }
                return Class.forName(name);
        }
    }

    private static Class<?>[] resolveTypes(List<Object> names, ClassLoader loader) throws Exception {
        Class<?>[] out = new Class<?>[names.size()];
        for (int i = 0; i < names.size(); i++) {
            out[i] = resolveType(String.valueOf(names.get(i)), loader);
        }
        return out;
    }

    private static boolean typeMatches(String expected, Class<?> actual, ClassLoader loader) throws Exception {
        if (expected == null || expected.isEmpty()) return true;
        if (actual.getName().equals(expected)) return true;
        if (actual.getSimpleName().equals(expected)) return true;
        // Cho phep ghi "String" thay cho "java.lang.String" va nguoc lai.
        try {
            Class<?> exp = resolveType(expected, loader);
            return exp != null && exp == actual;
        } catch (Exception e) {
            return false;
        }
    }

    private static String joinTypeNames(Class<?>[] types) {
        List<String> names = new ArrayList<>();
        for (Class<?> t : types) names.add(t.getName());
        return String.join(", ", names);
    }

    private static String describeModifiers(List<Object> mods) {
        List<String> out = new ArrayList<>();
        for (Object m : mods) out.add(String.valueOf(m));
        return String.join(" ", out);
    }

    private static List<String> missingModifiers(int mods, List<Object> expected) {
        List<String> missing = new ArrayList<>();
        for (Object o : expected) {
            String m = String.valueOf(o);
            boolean ok;
            switch (m) {
                case "public": ok = Modifier.isPublic(mods); break;
                case "private": ok = Modifier.isPrivate(mods); break;
                case "protected": ok = Modifier.isProtected(mods); break;
                case "static": ok = Modifier.isStatic(mods); break;
                case "final": ok = Modifier.isFinal(mods); break;
                case "abstract": ok = Modifier.isAbstract(mods); break;
                case "transient": ok = Modifier.isTransient(mods); break;
                case "volatile": ok = Modifier.isVolatile(mods); break;
                case "synchronized": ok = Modifier.isSynchronized(mods); break;
                default: ok = false; break;
            }
            if (!ok) missing.add(m);
        }
        return missing;
    }

    private static Object[] convertAll(List<Object> jsonValues, Class<?>[] targets) throws Exception {
        Object[] out = new Object[jsonValues.size()];
        for (int i = 0; i < jsonValues.size(); i++) {
            out[i] = convert(jsonValues.get(i), targets[i]);
        }
        return out;
    }

    private static Object convert(Object value, Class<?> target) throws Exception {
        if (value == null) {
            if (target.isPrimitive()) throw new IllegalArgumentException("null for primitive " + target.getName());
            return null;
        }
        if (target == String.class) return String.valueOf(value);
        if (target == boolean.class || target == Boolean.class) {
            if (value instanceof Boolean) return value;
            return Boolean.parseBoolean(String.valueOf(value));
        }
        if (target == char.class || target == Character.class) {
            String s = String.valueOf(value);
            if (s.length() != 1) throw new IllegalArgumentException("expected single char, got: " + s);
            return s.charAt(0);
        }
        if (value instanceof Number) {
            Number n = (Number) value;
            if (target == int.class || target == Integer.class) return n.intValue();
            if (target == long.class || target == Long.class) return n.longValue();
            if (target == double.class || target == Double.class) return n.doubleValue();
            if (target == float.class || target == Float.class) return n.floatValue();
            if (target == byte.class || target == Byte.class) return n.byteValue();
            if (target == short.class || target == Short.class) return n.shortValue();
        }
        if (value instanceof String && target.isEnum()) {
            @SuppressWarnings({"unchecked", "rawtypes"})
            Object e = Enum.valueOf((Class<Enum>) target, (String) value);
            return e;
        }
        if (target.isInstance(value)) return value;
        throw new IllegalArgumentException("cannot convert " + value + " to " + target.getName());
    }

    private static boolean valuesEqual(Object expected, Object actual) {
        if (expected == null) return actual == null;
        if (actual == null) return false;
        if (expected instanceof Number && actual instanceof Number) {
            double e = ((Number) expected).doubleValue();
            double a = ((Number) actual).doubleValue();
            // So thuc: sai so tuyet doi + tuong doi, tranh loi lam tron.
            if (expected instanceof Double || expected instanceof Float
                    || actual instanceof Double || actual instanceof Float) {
                double tol = 1e-9 * Math.max(1.0, Math.abs(e));
                return Math.abs(e - a) <= tol;
            }
            return ((Number) expected).longValue() == ((Number) actual).longValue();
        }
        if (expected instanceof Boolean || actual instanceof Boolean) {
            return String.valueOf(expected).equals(String.valueOf(actual));
        }
        return String.valueOf(expected).equals(String.valueOf(actual));
    }

    // ---------------- Small JSON helpers (no external dependency) ----------------

    private static String getString(Map<String, Object> m, String key, String def) {
        Object v = m.get(key);
        return v == null ? def : String.valueOf(v);
    }

    private static int getInt(Map<String, Object> m, String key, int def) {
        Object v = m.get(key);
        if (v instanceof Number) return ((Number) v).intValue();
        if (v instanceof String) {
            try { return Integer.parseInt((String) v); } catch (Exception ignored) { }
        }
        return def;
    }

    static class Json {
        static String escape(String s) {
            if (s == null) return "";
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < s.length(); i++) {
                char c = s.charAt(i);
                switch (c) {
                    case '"': sb.append("\\\""); break;
                    case '\\': sb.append("\\\\"); break;
                    case '\n': sb.append("\\n"); break;
                    case '\r': sb.append("\\r"); break;
                    case '\t': sb.append("\\t"); break;
                    case '\b': sb.append("\\b"); break;
                    case '\f': sb.append("\\f"); break;
                    default:
                        if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                        else sb.append(c);
                }
            }
            return sb.toString();
        }

        static String stringify(Object v) {
            if (v == null) return "null";
            if (v instanceof String) return "\"" + escape((String) v) + "\"";
            if (v instanceof Number || v instanceof Boolean) return String.valueOf(v);
            if (v instanceof Map) {
                @SuppressWarnings("unchecked")
                Map<String, Object> m = (Map<String, Object>) v;
                List<String> parts = new ArrayList<>();
                for (Map.Entry<String, Object> e : m.entrySet()) {
                    parts.add("\"" + escape(e.getKey()) + "\":" + stringify(e.getValue()));
                }
                return "{" + String.join(",", parts) + "}";
            }
            if (v instanceof List) {
                List<?> list = (List<?>) v;
                List<String> parts = new ArrayList<>();
                for (Object item : list) parts.add(stringify(item));
                return "[" + String.join(",", parts) + "]";
            }
            return "\"" + escape(String.valueOf(v)) + "\"";
        }
    }

    static class JsonParser {
        private final String s;
        private int pos = 0;
        JsonParser(String s) { this.s = s; }

        Object parseValue() throws Exception {
            skipWs();
            if (pos >= s.length()) throw new RuntimeException("unexpected end of JSON");
            char c = s.charAt(pos);
            if (c == '{') return parseObject();
            if (c == '[') return parseArray();
            if (c == '"') return parseString();
            if (c == 't') { expect("true"); return Boolean.TRUE; }
            if (c == 'f') { expect("false"); return Boolean.FALSE; }
            if (c == 'n') { expect("null"); return null; }
            return parseNumber();
        }

        private Map<String, Object> parseObject() throws Exception {
            Map<String, Object> map = new LinkedHashMap<>();
            pos++; // {
            skipWs();
            if (pos < s.length() && s.charAt(pos) == '}') { pos++; return map; }
            while (true) {
                skipWs();
                String key = parseString();
                skipWs();
                if (pos >= s.length() || s.charAt(pos) != ':') throw new RuntimeException("expected ':' in object");
                pos++;
                Object value = parseValue();
                map.put(key, value);
                skipWs();
                if (pos < s.length() && s.charAt(pos) == ',') { pos++; continue; }
                if (pos < s.length() && s.charAt(pos) == '}') { pos++; break; }
                throw new RuntimeException("expected ',' or '}' in object");
            }
            return map;
        }

        private List<Object> parseArray() throws Exception {
            List<Object> list = new ArrayList<>();
            pos++; // [
            skipWs();
            if (pos < s.length() && s.charAt(pos) == ']') { pos++; return list; }
            while (true) {
                list.add(parseValue());
                skipWs();
                if (pos < s.length() && s.charAt(pos) == ',') { pos++; continue; }
                if (pos < s.length() && s.charAt(pos) == ']') { pos++; break; }
                throw new RuntimeException("expected ',' or ']' in array");
            }
            return list;
        }

        private String parseString() throws Exception {
            if (s.charAt(pos) != '"') throw new RuntimeException("expected string");
            pos++;
            StringBuilder sb = new StringBuilder();
            while (pos < s.length()) {
                char c = s.charAt(pos++);
                if (c == '"') return sb.toString();
                if (c == '\\') {
                    if (pos >= s.length()) break;
                    char e = s.charAt(pos++);
                    switch (e) {
                        case '"': sb.append('"'); break;
                        case '\\': sb.append('\\'); break;
                        case '/': sb.append('/'); break;
                        case 'b': sb.append('\b'); break;
                        case 'f': sb.append('\f'); break;
                        case 'n': sb.append('\n'); break;
                        case 'r': sb.append('\r'); break;
                        case 't': sb.append('\t'); break;
                        case 'u':
                            if (pos + 4 > s.length()) throw new RuntimeException("bad unicode escape");
                            sb.append((char) Integer.parseInt(s.substring(pos, pos + 4), 16));
                            pos += 4;
                            break;
                        default: sb.append(e); break;
                    }
                } else {
                    sb.append(c);
                }
            }
            throw new RuntimeException("unterminated string");
        }

        private Number parseNumber() throws Exception {
            int start = pos;
            while (pos < s.length() && "-+0123456789.eE".indexOf(s.charAt(pos)) >= 0) pos++;
            String token = s.substring(start, pos);
            if (token.isEmpty()) throw new RuntimeException("invalid number");
            try {
                if (token.contains(".") || token.contains("e") || token.contains("E")) {
                    return Double.parseDouble(token);
                }
                return Long.parseLong(token);
            } catch (NumberFormatException e) {
                throw new RuntimeException("invalid number: " + token);
            }
        }

        private void expect(String word) throws Exception {
            if (!s.startsWith(word, pos)) throw new RuntimeException("expected " + word);
            pos += word.length();
        }

        private void skipWs() {
            while (pos < s.length() && Character.isWhitespace(s.charAt(pos))) pos++;
        }
    }
}
