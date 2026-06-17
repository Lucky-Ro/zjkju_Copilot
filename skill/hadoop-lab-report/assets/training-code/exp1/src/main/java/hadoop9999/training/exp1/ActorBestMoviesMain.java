package hadoop9999.training.exp1;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.io.NullWritable;
import org.apache.hadoop.mapreduce.Job;
import org.apache.hadoop.mapreduce.lib.input.FileInputFormat;
import org.apache.hadoop.mapreduce.lib.output.FileOutputFormat;

/**
 * MapReduce 驱动:输入 = HDFS 上的 Film.json,输出 = 「我的演员」的电影按评分(同分年份近者优先)排序。
 * fastjson 依赖 jar 通过 addFileToClassPath 从 HDFS /lib/fastjson-1.2.62.jar 加入分布式 classpath,
 * 所以运行前要先把 fastjson-1.2.62.jar 上传到 HDFS /lib/。
 * 用法:hadoop jar <本包>.jar <输入HDFS路径/Film.json> <输出HDFS目录>
 */
public class ActorBestMoviesMain {

	public static void main(String[] args) throws Exception{
		// 创建一个 job
		Job job = Job.getInstance(new Configuration());
		job.setJarByClass(ActorBestMoviesMain.class);
		//这里访问的是 HDFS 上 jar 包路径
		job.addFileToClassPath(new Path("/lib/fastjson-1.2.62.jar"));
		// 指定 job 的 mapper 和输出的类型 k2 v2
		job.setMapperClass(ActorBestMoviesMapper.class);
		job.setMapOutputKeyClass(MovieInfo.class);
		job.setMapOutputValueClass(NullWritable.class);
		//job.setSortComparatorClass(cls);
		// 指定 job 的输入和输出的路径
		FileInputFormat.setInputPaths(job, new Path(args[0]));
		FileOutputFormat.setOutputPath(job, new Path(args[1]));
		// 执行任务
		job.waitForCompletion(true);
	}
}
